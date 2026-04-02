from pdfminer.layout import LAParams
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfparser import PDFParser
import pdfminer
import logging
from operator import itemgetter
from dotenv import load_dotenv
import hashlib
import re, json, requests, urllib.request, urllib.error, urllib.parse,traceback, os, sys


#Logging
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(lineno)d - %(message)s')
streamHandler = logging.StreamHandler(sys.stdout)
streamHandler.setFormatter(formatter)

#Main Logger
parser_logFile='menuParser.log'
parser_logger = logging.getLogger('menuparser')
parser_logger.setLevel(logging.DEBUG)
parser_fh = logging.FileHandler(parser_logFile)
parser_fh.setFormatter(formatter)
parser_logger.addHandler(parser_fh)
parser_logger.addHandler(streamHandler)

#Smartsheet Logger
smartsheet_logFile='menuParser-smartsheet.log'
smartsheet_logger = logging.getLogger('menuparser.smartsheet')
smartsheet_logger.setLevel(logging.DEBUG)
smartsheet_fh = logging.FileHandler(smartsheet_logFile)
smartsheet_fh.setFormatter(formatter)
smartsheet_logger.addHandler(smartsheet_fh)

#pdf Logger
pdf_logFile='menuParser-pdf.log'
pdf_logger = logging.getLogger('menuparser.pdf')
pdf_logger.setLevel(logging.DEBUG)
pdf_fh = logging.FileHandler(pdf_logFile)
pdf_fh.setFormatter(formatter)
pdf_logger.addHandler(pdf_fh)

mealie_ingredient_nlp_enabled = False
mealie_category_cache = None
mealie_tag_cache = None

'''
get the smartsheet data
TODO: replace with sdk
'''
def getSheet(sheetID):
    url = 'https://%s/2.0/sheets/%s'%(server,sheetID)
    r = requests.get(url, headers=headers, verify=sslVerify)
    rArr = r.json()
    return rArr

def getAttachments(sheetID):
    url = 'https://%s/2.0/sheets/%s/attachments?includeAll=True'%(server,sheetID)
    r = requests.get(url, headers=headers, verify=sslVerify)
    rArr = r.json()
    return rArr

def getAttachment(sheetID,attachmentID):
    url = 'https://%s/2.0/sheets/%s/attachments/%s'%(server,sheetID,attachmentID)
    r = requests.get(url, headers=headers, verify=sslVerify)
    rArr = r.json()
    return rArr

def insertRows(sheetId,data):
    jsonData = json.dumps(data)
    url = 'https://%s/2.0/sheets/%s/rows'%(server,sheetID)
    r = requests.post(url, data=jsonData, headers=headers, verify=sslVerify)
    return r.json()

def updateRow(sheetId,rowId,data):
    data = json.dumps(data)
    url = 'https://%s/2.0/sheets/%s/rows'%(server,sheetID)
    r = requests.put(url, data=data, headers=headers, verify=sslVerify)
    return r

def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ('true', '1', 'yes', 'y', 'on')


def normalize_ingredient_lines(raw_ingredients):
    ingredient_lines = []
    for ingredient_line in raw_ingredients.split('\n'):
        ingredient_line = ingredient_line.strip()
        if not ingredient_line:
            continue
        if re.match(r'^[-—_]{5,}$', ingredient_line):
            continue
        ingredient_lines.append(ingredient_line)
    return ingredient_lines


def clean_recipe_name_text(text):
    cleaned = str(text or '')
    cleaned = re.sub(r'(?i)\bno\s+staples\s+for\s+this\s+meal\b', '', cleaned)
    cleaned = re.sub(r'(?i)\+?\s*nutritional\s+info(?:rmation)?\b', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' +,-')
    return cleaned


def slugify_recipe_name(name):
    slug = re.sub(r'[^a-z0-9]+', '-', str(name or '').lower()).strip('-')
    return slug


def extract_time_line(raw_time_text):
    parts = [part.strip() for part in str(raw_time_text or '').split('\n') if part and part.strip()]
    for part in parts:
        if re.search(r'\d', part):
            return part
    return ''


def normalize_time_value(raw_time):
    text = extract_time_line(raw_time)
    if not text:
        return None

    text = re.sub(r'\s+', ' ', text).strip().lower()
    text = re.sub(r'\b(hours?|hrs?)\b', 'h', text)
    text = re.sub(r'\b(minutes?|mins?)\b', 'm', text)
    text = re.sub(r'\bhr\b', 'h', text)
    text = re.sub(r'\bmin\b', 'm', text)

    hours_match = re.search(r'(\d+)\s*h', text)
    minutes_match = re.search(r'(\d+)\s*m', text)
    hours = hours_match.group(1) if hours_match else None
    minutes = minutes_match.group(1) if minutes_match else None

    if not hours and not minutes:
        return None
    if hours and minutes:
        return f'{hours}h {minutes}m'
    if hours:
        return f'{hours}h'
    return f'{minutes}m'


def extract_time_values(raw_time_text):
    text = str(raw_time_text or '')
    text = re.sub(r'\b(hours?|hrs?)\b', 'h', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(minutes?|mins?)\b', 'm', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhr\b', 'h', text, flags=re.IGNORECASE)
    text = re.sub(r'\bmin\b', 'm', text, flags=re.IGNORECASE)

    values = []
    for match in re.finditer(r'(\d+\s*h(?:\s*\d+\s*m)?|\d+\s*m)', text, flags=re.IGNORECASE):
        value = re.sub(r'\s+', '', match.group(1).lower())
        if re.search(r'\d', value):
            values.append(value)
    return values


def time_text_to_minutes(time_text):
    normalized = normalize_time_value(time_text)
    if not normalized:
        return None

    hours_match = re.search(r'(\d+)h', normalized)
    minutes_match = re.search(r'(\d+)m', normalized)

    hours = int(hours_match.group(1)) if hours_match else 0
    minutes = int(minutes_match.group(1)) if minutes_match else 0
    total_minutes = (hours * 60) + minutes
    return total_minutes if total_minutes > 0 else None


def minutes_to_time_value(total_minutes):
    try:
        total_minutes = int(total_minutes)
    except (TypeError, ValueError):
        return None

    if total_minutes <= 0:
        return None

    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours and minutes:
        return f'{hours}h {minutes}m'
    if hours:
        return f'{hours}h'
    return f'{minutes}m'


def category_slug(name):
    slug = re.sub(r'[^a-z0-9]+', '-', str(name or '').strip().lower())
    return slug.strip('-')


def extract_recipe_categories(menu_type_text):
    type_text = str(menu_type_text or '').strip()
    if not type_text:
        return []

    parts = re.split(r'\s*[|,;/]\s*', type_text)
    if len(parts) == 1:
        parts = [type_text]

    categories = []
    seen_slugs = set()
    for part in parts:
        name = part.strip()
        if not name:
            continue
        slug = category_slug(name)
        if not slug or slug in seen_slugs:
            continue
        categories.append({'name': name, 'slug': slug})
        seen_slugs.add(slug)
    return categories


def extract_recipe_tags(*tag_values):
    tags = []
    seen_slugs = set()
    for tag_value in tag_values:
        value = str(tag_value or '').strip()
        if not value:
            continue
        slug = category_slug(value)
        if not slug or slug in seen_slugs:
            continue
        tags.append({'name': value, 'slug': slug})
        seen_slugs.add(slug)
    return tags


def prefixed_tag_value(prefix, value):
    text = str(value or '').strip()
    if not text:
        return ''
    return text


def mealie_load_category_cache(force_refresh=False):
    global mealie_category_cache
    if mealie_category_cache is not None and not force_refresh:
        return mealie_category_cache

    mealie_category_cache = {}
    url = mealie_build_url('/api/organizers/categories')
    page = 1
    per_page = 100
    while True:
        response = requests.get(url, params={'page': page, 'perPage': per_page}, headers=mealie_headers, verify=sslVerify)
        if response.status_code >= 300:
            parser_logger.warning('Failed loading Mealie categories (%s): %s', response.status_code, response.text)
            return mealie_category_cache

        payload = response.json() or {}
        items = payload.get('items') or []
        if not items:
            break

        for item in items:
            slug = str(item.get('slug') or '').strip().lower()
            if not slug:
                continue
            mealie_category_cache[slug] = {
                'id': item.get('id'),
                'name': item.get('name'),
                'slug': item.get('slug'),
            }

        if len(items) < per_page:
            break
        page += 1
    return mealie_category_cache


def mealie_resolve_recipe_categories(category_candidates):
    if not category_candidates:
        return []

    cache = mealie_load_category_cache()
    resolved = []

    for category in category_candidates:
        slug = str(category.get('slug') or '').strip().lower()
        name = str(category.get('name') or '').strip()
        if not slug or not name:
            continue

        existing = cache.get(slug)
        if existing and existing.get('id'):
            resolved.append(existing)
            continue

        create_url = mealie_build_url('/api/organizers/categories')
        create_payload = {
            'name': name,
            'slug': slug,
        }
        create_response = requests.post(create_url, data=json.dumps(create_payload), headers=mealie_headers, verify=sslVerify)
        if create_response.status_code >= 300:
            refreshed = mealie_load_category_cache(force_refresh=True).get(slug)
            if refreshed and refreshed.get('id'):
                resolved.append(refreshed)
                continue
            parser_logger.warning('Failed creating Mealie category %s (%s): %s', name, create_response.status_code, create_response.text)
            continue

        created = create_response.json() or {}
        normalized = {
            'id': created.get('id'),
            'name': created.get('name', name),
            'slug': created.get('slug', slug),
        }
        if normalized.get('id'):
            cache[slug] = normalized
            resolved.append(normalized)

    return resolved


def mealie_load_tag_cache(force_refresh=False):
    global mealie_tag_cache
    if mealie_tag_cache is not None and not force_refresh:
        return mealie_tag_cache

    mealie_tag_cache = {}
    url = mealie_build_url('/api/organizers/tags')
    page = 1
    per_page = 100
    while True:
        response = requests.get(url, params={'page': page, 'perPage': per_page}, headers=mealie_headers, verify=sslVerify)
        if response.status_code >= 300:
            parser_logger.warning('Failed loading Mealie tags (%s): %s', response.status_code, response.text)
            return mealie_tag_cache

        payload = response.json() or {}
        items = payload.get('items') or []
        if not items:
            break

        for item in items:
            slug = str(item.get('slug') or '').strip().lower()
            if not slug:
                continue
            mealie_tag_cache[slug] = {
                'id': item.get('id'),
                'name': item.get('name'),
                'slug': item.get('slug'),
            }

        if len(items) < per_page:
            break
        page += 1
    return mealie_tag_cache


def mealie_resolve_recipe_tags(tag_candidates):
    if not tag_candidates:
        return []

    cache = mealie_load_tag_cache()
    resolved = []

    for tag in tag_candidates:
        slug = str(tag.get('slug') or '').strip().lower()
        name = str(tag.get('name') or '').strip()
        if not slug or not name:
            continue

        existing = cache.get(slug)
        if existing and existing.get('id'):
            resolved.append(existing)
            continue

        create_url = mealie_build_url('/api/organizers/tags')
        create_payload = {
            'name': name,
            'slug': slug,
        }
        create_response = requests.post(create_url, data=json.dumps(create_payload), headers=mealie_headers, verify=sslVerify)
        if create_response.status_code >= 300:
            refreshed = mealie_load_tag_cache(force_refresh=True).get(slug)
            if refreshed and refreshed.get('id'):
                resolved.append(refreshed)
                continue
            parser_logger.warning('Failed creating Mealie tag %s (%s): %s', name, create_response.status_code, create_response.text)
            continue

        created = create_response.json() or {}
        normalized = {
            'id': created.get('id'),
            'name': created.get('name', name),
            'slug': created.get('slug', slug),
        }
        if normalized.get('id'):
            cache[slug] = normalized
            resolved.append(normalized)

    return resolved


def extract_nutrition_raw_text(*texts):
    combined = '\n'.join([str(text or '') for text in texts if text])
    if not combined.strip():
        return ''

    match = re.search(r'(Nutrition(?:al)?\s*Facts?[:\s].*)', combined, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ''

    raw = match.group(1).strip()
    return re.sub(r'\n{3,}', '\n\n', raw)


def extract_nutrition_fields(*texts):
    primary_text = str(texts[0] or '') if texts else ''
    combined = ' '.join([str(text or '') for text in texts if text])
    combined = re.sub(r'\s+', ' ', combined)
    combined = combined.replace(',', '')

    patterns = {
        'calories': (r'Calories?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)', 'kcal'),
        'fatContent': (r'(?:Total\s+)?Fat(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg)?', 'g'),
        'saturatedFatContent': (r'(?:Saturated|Sat\.?)\s*Fat(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg)?', 'g'),
        'transFatContent': (r'Trans\s+Fat(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg)?', 'g'),
        'unsaturatedFatContent': (r'Unsaturated\s+Fat(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg)?', 'g'),
        'cholesterolContent': (r'Cholesterol(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(mg|g)?', 'mg'),
        'sodiumContent': (r'Sodium(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(mg|g)?', 'mg'),
        'carbohydrateContent': (r'(?:Carbs?|Carbohydrates?|Carb)(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg)?', 'g'),
        'fiberContent': (r'Fiber(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg)?', 'g'),
        'proteinContent': (r'Protein(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg)?', 'g'),
    }

    nutrition = {}
    for field, (pattern, default_unit) in patterns.items():
        match = re.search(pattern, combined, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        unit = default_unit
        if match.lastindex and match.lastindex >= 2:
            unit = (match.group(2) or default_unit).lower()
        nutrition[field] = f'{value}{unit}'

    total_sugar_match = re.search(r'(?:Sugars?|T\.?\s*Sugs?)(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg)?', combined, flags=re.IGNORECASE)
    added_sugar_match = re.search(r'(?:Added\s+Sugars?|A\.?\s*Sugs?)(?:\s*\([^)]*\))?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)\s*(g|mg)?', combined, flags=re.IGNORECASE)

    selected_sugar_match = total_sugar_match or added_sugar_match
    if selected_sugar_match:
        sugar_value = selected_sugar_match.group(1)
        sugar_unit = str(selected_sugar_match.group(2) or 'g').lower()
        nutrition['sugarContent'] = f'{sugar_value}{sugar_unit}'

    if primary_text and re.search(r'Nutritional\s+Information', primary_text, flags=re.IGNORECASE):
        numeric_lines = re.findall(r'(?m)^\s*([0-9]+(?:\.[0-9]+)?)\s*$', primary_text)
        servings_value = extract_servings_value(primary_text)

        if servings_value is not None and numeric_lines:
            try:
                if float(numeric_lines[0]) == float(servings_value):
                    numeric_lines = numeric_lines[1:]
            except ValueError:
                pass

        fallback_fields = [
            ('carbohydrateContent', 'g'),
            ('fiberContent', 'g'),
            ('fatContent', 'g'),
            ('sugarContent', 'g'),
        ]
        value_index = 0
        for field, unit in fallback_fields:
            if field in nutrition:
                continue
            if value_index >= len(numeric_lines):
                break
            nutrition[field] = f"{numeric_lines[value_index]}{unit}"
            value_index += 1

    return nutrition


def extract_servings_value(*texts):
    combined = '\n'.join([str(text or '') for text in texts if text])
    if not combined.strip():
        return None

    normalized = re.sub(r'\s+', ' ', combined)
    patterns = [
        r'Servings?\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?)',
        r'Main\s+([0-9]+(?:\.[0-9]+)?)',
        r'Serving\s*s?\s*([0-9]+(?:\.[0-9]+)?)',
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            continue

    return None


def build_raw_ingredient(line):
    return {
        'originalText': line,
        'title': line,
    }


def should_fallback_to_raw_ingredient(source_line, parsed_ingredient):
    if not parsed_ingredient:
        return True

    source = (source_line or '').strip().lower()
    display = str(parsed_ingredient.get('display') or '').strip().lower()
    note = str(parsed_ingredient.get('note') or '').strip().lower()
    food_name = str(((parsed_ingredient.get('food') or {}).get('name')) or '').strip().lower()

    if '(' in source and ')' in source:
        return True

    if re.search(r'\b(pkg|package)\b', source):
        return True

    if re.search(r'[¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]', source):
        return True

    if ' or ' in display or note.startswith('or '):
        return True

    if food_name in ('pkg', 'package'):
        return True

    return False


def normalize_mealie_url(raw_url):
    if not raw_url:
        return raw_url
    normalized = str(raw_url).strip().rstrip('/')
    if normalized.endswith('/api'):
        normalized = normalized[:-4]
    return normalized


def mealie_build_url(path):
    base = (mealie_url or '').rstrip('/')
    if not path.startswith('/'):
        path = '/' + path
    return '%s%s'%(base, path)


def mealie_preflight_check():
    openapi_url = mealie_build_url('/openapi.json')
    try:
        response = requests.get(openapi_url, headers=mealie_headers, verify=sslVerify, timeout=15)
    except requests.RequestException as exc:
        parser_logger.error('Mealie preflight failed connecting to %s: %s', openapi_url, exc)
        return False

    if response.status_code >= 300:
        parser_logger.error('Mealie preflight failed (%s) at %s: %s', response.status_code, openapi_url, response.text)
        return False

    try:
        payload = response.json()
    except ValueError:
        body_preview = (response.text or '').strip().replace('\n', ' ')[:200]
        parser_logger.error('Mealie preflight expected JSON at %s but got non-JSON response: %s', openapi_url, body_preview)
        return False

    api_title = ((payload.get('info') or {}).get('title') or '').strip().lower()
    if api_title != 'mealie':
        parser_logger.error('Mealie preflight found unexpected API title at %s: %s', openapi_url, api_title or '<missing>')
        return False

    return True


def mealie_parse_ingredients(ingredient_lines):
    if not ingredient_lines:
        return []

    parse_url = mealie_build_url('/api/parser/ingredient')
    filtered_lines = []
    for line in ingredient_lines:
        stripped = (line or '').strip()
        if not stripped:
            continue
        if re.match(r'^[-—_]{5,}$', stripped):
            continue
        filtered_lines.append(stripped)

    if not filtered_lines:
        return []

    structured = []
    for source_line in filtered_lines:
        parse_payload = {
            'ingredient': source_line,
        }

        try:
            response = requests.post(parse_url, data=json.dumps(parse_payload), headers=mealie_headers, verify=sslVerify, timeout=30)
        except requests.RequestException as exc:
            parser_logger.warning('Mealie ingredient parse request failed for "%s": %s', source_line, exc)
            structured.append(build_raw_ingredient(source_line))
            continue

        if response.status_code >= 300:
            parser_logger.warning('Mealie ingredient parse failed (%s) for "%s": %s', response.status_code, source_line, response.text)
            structured.append(build_raw_ingredient(source_line))
            continue

        try:
            parsed_payload = response.json()
        except ValueError:
            parser_logger.warning('Mealie ingredient parse returned invalid JSON for "%s": %s', source_line, response.text)
            structured.append(build_raw_ingredient(source_line))
            continue

        ingredient = (parsed_payload or {}).get('ingredient') or {}
        if should_fallback_to_raw_ingredient(source_line, ingredient):
            structured.append(build_raw_ingredient(source_line))
            continue

        unit_obj = ingredient.get('unit') or {}
        food_obj = ingredient.get('food') or {}

        normalized = {
            'quantity': ingredient.get('quantity'),
            'unit': {
                'id': unit_obj.get('id'),
                'name': unit_obj.get('name'),
            } if unit_obj.get('id') and unit_obj.get('name') else None,
            'food': {
                'id': food_obj.get('id'),
                'name': food_obj.get('name'),
            } if food_obj.get('id') and food_obj.get('name') else None,
            'note': ingredient.get('note') or '',
            'title': source_line,
            'originalText': source_line,
        }
        structured.append(normalized)
    return structured


def mealie_get_recipes(search_term):
    url = mealie_build_url('/api/recipes')
    params = {
        'search': search_term,
        'perPage': 50,
    }
    response = requests.get(url, params=params, headers=mealie_headers, verify=sslVerify)
    if response.status_code >= 300:
        parser_logger.error('Mealie recipe search failed (%s): %s', response.status_code, response.text)
        return []
    payload = response.json()
    return payload.get('items', [])


def mealie_find_slug_by_exact_name(recipe_name):
    target = str(recipe_name or '').strip().lower()
    if not target:
        return None

    # First pass: search endpoint
    for recipe in mealie_get_recipes(recipe_name):
        if str(recipe.get('name') or '').strip().lower() == target:
            return recipe.get('slug')

    # Second pass: paginated full scan as fallback
    page = 1
    while True:
        url = mealie_build_url('/api/recipes')
        response = requests.get(url, params={'perPage': 100, 'page': page}, headers=mealie_headers, verify=sslVerify)
        if response.status_code >= 300:
            return None
        payload = response.json() or {}
        items = payload.get('items') or []
        if not items:
            return None
        for recipe in items:
            if str(recipe.get('name') or '').strip().lower() == target:
                return recipe.get('slug')
        page += 1


def mealie_get_recipe(slug):
    url = mealie_build_url('/api/recipes/%s'%(slug))
    response = requests.get(url, headers=mealie_headers, verify=sslVerify)
    if response.status_code >= 300:
        parser_logger.error('Mealie get recipe failed (%s): %s', response.status_code, response.text)
        return None
    return response.json()


def find_mealie_recipe_slug(menu_key, recipe_name):
    recipes = mealie_get_recipes(recipe_name)
    name_match_slug = None
    for recipe in recipes:
        slug = recipe.get('slug')
        if not slug:
            continue
        if recipe.get('name') == recipe_name and not name_match_slug:
            name_match_slug = slug
        recipe_detail = mealie_get_recipe(slug)
        if not recipe_detail:
            continue
        extras = recipe_detail.get('extras') or {}
        if extras.get('menuParserKey') == menu_key:
            return slug
    return name_match_slug


def build_mealie_recipe_payload(meal, meal_type, plan_source, source_row_id):
    main_dish = clean_recipe_name_text(meal.get('mainDish', ''))
    side_dish = clean_recipe_name_text(meal.get('sideDish', ''))

    recipe_name = main_dish
    if side_dish:
        recipe_name = recipe_name + ' + ' + side_dish

    menu_key_source = '%s|%s|%s|%s|%s'%(plan_source, meal_type, meal.get('number', ''), main_dish, side_dish)
    menu_key = hashlib.sha1(menu_key_source.encode('utf-8')).hexdigest()

    meal_number_value = str(meal.get('number', '')).strip()
    menu_type_label_value = str(meal.get('type', '')).strip()

    effective_meal_type = str(meal_type or '').strip()
    if effective_meal_type.lower() == 'meal' and re.search(r'\b8\b', meal_number_value):
        effective_meal_type = 'Drink'
    if re.search(r'^\s*drink\s+idea\s*$', menu_type_label_value, flags=re.IGNORECASE):
        effective_meal_type = 'Drink'

    ingredient_lines = normalize_ingredient_lines(meal.get('ingredients', ''))

    ingredients = []
    for ingredient_line in ingredient_lines:
        ingredients.append({
            'note': ingredient_line,
            'originalText': ingredient_line,
            'title': ingredient_line,
        })

    instruction_lines = []
    for instruction_line in meal.get('instructions', '').split('\n'):
        instruction_line = instruction_line.strip()
        if instruction_line:
            instruction_lines.append(instruction_line)

    instructions = []
    if instruction_lines:
        instructions.append({
            'title': '',
            'summary': '',
            'text': ' '.join(instruction_lines),
            'ingredientReferences': [],
        })

    category_candidates = extract_recipe_categories(meal.get('type', ''))
    menu_type_slug = category_slug(effective_meal_type)
    if menu_type_slug and menu_type_slug not in [str(each.get('slug') or '').strip().lower() for each in category_candidates]:
        category_candidates.append({'name': str(effective_meal_type).strip(), 'slug': menu_type_slug})

    recipe_categories = mealie_resolve_recipe_categories(category_candidates)
    dish_role_value = str(meal.get('dishRole', '') or '').strip()
    side_dish_tag_value = 'Side Dish' if dish_role_value.lower() == 'side dish' else ''
    recipe_tags = mealie_resolve_recipe_tags(extract_recipe_tags(
        'Emeals',
        prefixed_tag_value('menuPlanSource', plan_source),
        prefixed_tag_value('menuType', effective_meal_type),
        prefixed_tag_value('mealNumber', meal_number_value),
        prefixed_tag_value('menuTypeLabel', menu_type_label_value),
        side_dish_tag_value,
    ))
    nutrition = extract_nutrition_fields(meal.get('nutritionText', ''), meal.get('ingredients', ''), meal.get('instructions', ''))
    servings_value = extract_servings_value(meal.get('nutritionText', ''))
    nutrition_raw = extract_nutrition_raw_text(meal.get('nutritionText', ''), meal.get('ingredients', ''), meal.get('instructions', ''))

    prep_time = normalize_time_value(meal.get('prep', ''))
    cook_time = normalize_time_value(meal.get('cook', ''))
    total_time = normalize_time_value(meal.get('total', ''))

    if not total_time and prep_time and cook_time:
        prep_minutes = time_text_to_minutes(prep_time)
        cook_minutes = time_text_to_minutes(cook_time)
        if prep_minutes is not None and cook_minutes is not None:
            total_time = minutes_to_time_value(prep_minutes + cook_minutes)

    payload = {
        'name': recipe_name,
        'description': 'Imported from eMeals plan: %s'%(plan_source),
        'prepTime': prep_time,
        'cookTime': cook_time,
        'performTime': cook_time,
        'totalTime': total_time,
        'recipeCategory': recipe_categories,
        'tags': recipe_tags,
        'recipeIngredient': ingredients,
        'recipeInstructions': instructions,
        'nutrition': nutrition if nutrition else None,
        'extras': {
            'menuParserKey': menu_key,
            'menuPlanSource': plan_source,
            'menuType': effective_meal_type,
            'mealNumber': meal_number_value,
            'sourceSmartsheetRowId': str(source_row_id),
            'menuTypeLabel': menu_type_label_value,
            'dishRole': dish_role_value,
            'nutritionRaw': nutrition_raw,
        }
    }

    if servings_value and servings_value > 0:
        payload['recipeServings'] = servings_value

    if nutrition:
        payload['settings'] = {
            'showNutrition': True,
        }

    return payload, menu_key


def upsert_mealie_recipe(meal, meal_type, plan_source, source_row_id):
    payload, menu_key = build_mealie_recipe_payload(meal, meal_type, plan_source, source_row_id)
    existing_slug = find_mealie_recipe_slug(menu_key, payload['name'])
    if not existing_slug:
        existing_slug = mealie_find_slug_by_exact_name(payload['name'])

    if existing_slug:
        existing_recipe = mealie_get_recipe(existing_slug)
        if existing_recipe and existing_recipe.get('name'):
            payload['name'] = existing_recipe.get('name')
        patch_url = mealie_build_url('/api/recipes/%s'%(existing_slug))
        patch_payload = dict(payload)
        patch_payload.pop('slug', None)
        response = requests.patch(patch_url, data=json.dumps(patch_payload), headers=mealie_headers, verify=sslVerify)
        if response.status_code >= 300:
            if response.status_code == 400 and 'Recipe already exists' in (response.text or ''):
                retry_payload = dict(patch_payload)
                retry_payload.pop('name', None)
                retry_response = requests.patch(patch_url, data=json.dumps(retry_payload), headers=mealie_headers, verify=sslVerify)
                if retry_response.status_code < 300:
                    parser_logger.info('Updated Mealie recipe (name preserved due duplicate): %s', payload['name'])
                    return True, existing_slug
            parser_logger.error('Failed updating Mealie recipe (%s): %s', response.status_code, response.text)
            return False, None
        parser_logger.info('Updated Mealie recipe: %s', payload['name'])
        return True, existing_slug

    create_url = mealie_build_url('/api/recipes')
    create_response = requests.post(create_url, data=json.dumps({'name': payload['name']}), headers=mealie_headers, verify=sslVerify)
    if create_response.status_code >= 300:
        response_text = create_response.text or ''
        if create_response.status_code == 400 and 'Recipe already exists' in response_text:
            fallback_slug = find_mealie_recipe_slug(menu_key, payload['name'])
            if not fallback_slug:
                fallback_slug = mealie_find_slug_by_exact_name(payload['name'])
            if not fallback_slug:
                fallback_slug = slugify_recipe_name(payload['name'])

            if fallback_slug:
                payload['slug'] = fallback_slug
                patch_url = mealie_build_url('/api/recipes/%s'%(fallback_slug))
                update_response = requests.patch(patch_url, data=json.dumps(payload), headers=mealie_headers, verify=sslVerify)
                if update_response.status_code < 300:
                    parser_logger.info('Updated existing Mealie recipe after duplicate create: %s', payload['name'])
                    return True, fallback_slug

        parser_logger.error('Failed creating Mealie recipe shell (%s): %s', create_response.status_code, create_response.text)
        return False, None

    create_body = create_response.json()
    created_slug = create_body if isinstance(create_body, str) else create_body.get('slug')
    if not created_slug:
        parser_logger.error('Unable to determine created Mealie slug for: %s', payload['name'])
        return False, None

    patch_url = mealie_build_url('/api/recipes/%s'%(created_slug))
    patch_payload = dict(payload)
    patch_payload.pop('slug', None)
    update_response = requests.patch(patch_url, data=json.dumps(patch_payload), headers=mealie_headers, verify=sslVerify)
    if update_response.status_code >= 300:
        if update_response.status_code == 400 and 'Recipe already exists' in (update_response.text or ''):
            retry_payload = dict(patch_payload)
            retry_payload.pop('name', None)
            retry_response = requests.patch(patch_url, data=json.dumps(retry_payload), headers=mealie_headers, verify=sslVerify)
            if retry_response.status_code < 300:
                parser_logger.info('Created Mealie recipe shell and updated fields (name preserved due duplicate): %s', payload['name'])
                return True, created_slug

            existing_slug = mealie_find_slug_by_exact_name(payload.get('name', ''))
            if existing_slug:
                fallback_payload = dict(patch_payload)
                fallback_payload.pop('name', None)
                fallback_patch_url = mealie_build_url('/api/recipes/%s'%(existing_slug))
                fallback_response = requests.patch(fallback_patch_url, data=json.dumps(fallback_payload), headers=mealie_headers, verify=sslVerify)
                if fallback_response.status_code < 300:
                    parser_logger.info('Updated existing Mealie recipe after create-shell duplicate: %s', payload['name'])
                    return True, existing_slug
        parser_logger.error('Failed updating created Mealie recipe (%s): %s', update_response.status_code, update_response.text)
        return False, None

    parser_logger.info('Created Mealie recipe: %s', payload['name'])
    return True, created_slug


def mealie_attach_pdf_asset(recipe_slug, pdf_path, asset_name):
    if not recipe_slug:
        return False
    if not pdf_path or not os.path.exists(pdf_path):
        parser_logger.info('Skipping Mealie recipe asset attach for %s; source PDF not available at %s', recipe_slug, pdf_path)
        return True

    recipe = mealie_get_recipe(recipe_slug)
    if not recipe:
        return False

    asset_basename = os.path.basename(str(asset_name or 'plan.pdf'))
    existing_assets = recipe.get('assets') or []
    for asset in existing_assets:
        if str(asset.get('name') or '').strip() == asset_basename:
            parser_logger.info('Mealie recipe asset already present for %s: %s', recipe_slug, asset_basename)
            return True

    upload_url = mealie_build_url('/api/recipes/%s/assets'%(recipe_slug))
    upload_headers = {
        'Authorization': mealie_headers.get('Authorization', ''),
    }

    with open(pdf_path, 'rb') as pdf_handle:
        files = {
            'file': (asset_basename, pdf_handle, 'application/pdf'),
        }
        data = {
            'name': asset_basename,
            'icon': 'mdi-file-pdf-box',
            'extension': 'pdf',
        }
        response = requests.post(upload_url, headers=upload_headers, data=data, files=files, verify=sslVerify)

    if response.status_code >= 300:
        parser_logger.warning('Failed attaching Mealie recipe asset %s to %s (%s): %s', asset_basename, recipe_slug, response.status_code, response.text)
        return False

    parser_logger.info('Attached Mealie recipe asset %s to %s', asset_basename, recipe_slug)
    return True


def expand_meal_recipe_entries(meals, meal_type):
    entries = []
    is_meal_plan = str(meal_type or '').strip().lower() == 'meal'

    for meal in meals:
        if not is_meal_plan:
            entries.append(meal)
            continue

        main_entry = dict(meal)
        main_entry['dishRole'] = 'Main Dish'
        main_entry['sideDish'] = ''
        main_entry['ingredients'] = meal.get('ingredientsMain', meal.get('ingredients', ''))
        main_entry['instructions'] = meal.get('instructionsMain', meal.get('instructions', ''))
        main_entry['nutritionText'] = meal.get('nutritionTextMain', meal.get('nutritionText', ''))
        entries.append(main_entry)

        side_name = str(meal.get('sideDish') or '').strip()
        if not side_name:
            continue

        side_entry = dict(meal)
        side_entry['dishRole'] = 'Side Dish'
        side_entry['mainDish'] = side_name
        side_entry['sideDish'] = ''
        side_entry['ingredients'] = meal.get('ingredientsSide', '')
        side_entry['instructions'] = meal.get('instructionsSide', '')
        side_entry['nutritionText'] = meal.get('nutritionTextSide', '')
        entries.append(side_entry)

    return entries


def upload_meals_to_mealie(meals, meal_type, plan_source, source_row_id, pdf_path=None, pdf_asset_name=None):
    all_success = True
    first_recipe_slug = None
    for meal in expand_meal_recipe_entries(meals, meal_type):
        result, saved_slug = upsert_mealie_recipe(meal, meal_type, plan_source, source_row_id)
        if not result:
            all_success = False
            continue
        if not first_recipe_slug and saved_slug:
            first_recipe_slug = saved_slug

    if first_recipe_slug and pdf_path and pdf_asset_name:
        asset_result = mealie_attach_pdf_asset(first_recipe_slug, pdf_path, pdf_asset_name)
        if not asset_result:
            all_success = False

    return all_success


'''
using the sheet data, get a dictionary of columnId's that we care about
'''
def getColumns(sheet):
    columnId ={}
    for column in sheet['columns']:
        if column['title'] == 'meal Title':
            columnId['mainDish'] = column['id']
        if column['title'] == 'side dishes':
            columnId['sideDish'] = column['id']
        if column['title'] == 'type':
            columnId['type'] = column['id']
        if column['title'] == 'Meal Number':
            columnId['number'] = column['id']
        if column['title'] == 'Prep Time':
            columnId['prep'] = column['id']
        if column['title'] == 'Cook Time':
            columnId['cook'] = column['id']
        if column['title'] == 'Total Time':
            columnId['total'] = column['id']
        if column['title'] == 'Ingredients':
            columnId['ingredients'] = column['id']
        if column['title'] == 'Instructions':
            columnId['instructions'] = column['id']
        if column['title'] == 'Process':
            columnId['process'] = column['id']
    return columnId

'''
Pull out and assemble the names of the dishes as well as the meal Type, if there is a type)
'''
def getDishes(food,height,meal_number=''):
    pdf_logger.info('Getting the dishes')
    pdf_logger.debug(height)

    menuLine =[]
    menuType = ''

    '''Get the lines pertaining to this meal'''
    for line in food:
        pdf_logger.debug(line)
        if int(line['height']) in range(int(height)-100,int(height)):
            menuLine.append(line)
        elif int(line['height']) in range(int(height),int(height)+3) and line['width'] < 193.0:
            menuType = line['text']

    menuLine = sorted(menuLine, key=lambda item: (-float(item.get('height', 0)), float(item.get('width', 0))))

    '''
    for each line, if it is the first one, assume it is the start of the main dish name
    otherwise, check the hieght compare to the first line, it is either a second line of a dish name,
    or the first of the side dish name.  if it side dish has been set it is probably the second line of that
    '''
    for num,each in enumerate(menuLine):
        pdf_logger.debug((str(num) + ' : ' + str(each)))
        if num == 0:
            mainDish = each['text']
        elif num > 0:
            diff = menuLine[num-1]['height'] - each['height']
            if int(diff) in range(9,15):
                try:
                    sideDish
                except NameError:
                    mainDish = mainDish + each['text']
                else:
                    sideDish = sideDish + each['text']
            elif diff > 20:
                sideDish = each['text']

    if re.search(r'^\s*Recipe\b', str(meal_number or ''), flags=re.IGNORECASE):
        title_candidates = []
        for each in menuLine:
            candidate_text = re.sub(r'\s+', ' ', str(each.get('text', '') or '')).strip()
            if not candidate_text:
                continue
            if re.search(r'Nutritional\s+Information|^Ingredients:?$|^Instructions:?$', candidate_text, flags=re.IGNORECASE):
                continue
            if re.search(r'(?i)\b(stir|serve|serving|combine|preheat|bake|whisk|minutes?|immediately)\b', candidate_text):
                continue
            if re.search(r'(?i)^(and|with|just)\b', candidate_text):
                continue
            if len(candidate_text) < 4:
                continue
            title_candidates.append(candidate_text)

        if title_candidates:
            mainDish = title_candidates[0]
        sideDish = ''


    '''if main dish isnt set set it to be empyt to prevent futre error (Not a very common issue and can be resolved by hand.  later TODO'''
    try:
        mainDish
    except NameError:
        mainDish = ''
    '''if side dish isnt set set it to be empyt to prevent futre error (there isn't always a side dish'''
    try:
        sideDish
    except NameError:
        sideDish = ''

    '''Strip leading/trailing whitespace, and remove line breaks'''
    mainDish = re.sub('\n',' ',mainDish.strip())
    sideDish = re.sub('\n',' ',sideDish.strip())
    menuType = re.sub('\n',' ',menuType.strip())
    pdf_logger.debug("Main Dish: %s, Side Dish: %s, Menu Type: %s"%(mainDish,sideDish,menuType))

    return mainDish,sideDish,menuType

'''
This function takes the ingrediends and the directions, gets the ones for the selected meal,
 and identifies the ingredients and directions secitons for use
'''
def getSteps(ingdir,height):
    pdf_logger.info('Getting the steps')
    pdf_logger.debug(height)
    pdf_logger.debug(ingdir)
    items=[]
    ingredients = ''
    instructions = ''

    '''find the pieces'''
    for item in ingdir:
        if int(item['height']) in range(int(height),int(height)+20) and (item['width'] == 193.0 or item['width'] == 389.0):
           pdf_logger.debug("height: %s, item: %s"%(height,item))
           items.append(item)

    '''sort them by horizontal alignment'''
    items = sorted(items,key=itemgetter('width'))
    pdf_logger.debug(items)
    '''remove the words Ingredients and Instructions for the first meal on each page'''

    for item in items:
        if item['width'] == 193.0:
            if item['text'].startswith('Ingredients:\n'):
                item['text'] = item['text'][13:len(item['text'])]
            if item['text'] == '':
                continue
            ingredients = item['text'].strip()
        elif item['width'] == 389.0:
            if item['text'].startswith('Instructions:\n'):
                item['text'] = item['text'][15:len(item['text'])]
            if item['text'] == '':
                continue
            instructions = item['text'].strip()

    pdf_logger.debug("ingredients: %s, instructions: %s"%(ingredients,instructions))
    return ingredients,instructions


def split_dual_section_text(raw_text):
    text = str(raw_text or '').strip()
    if not text:
        return '', ''

    parts = re.split(r'\n[-—_]{5,}\n', text, maxsplit=1)
    if len(parts) == 1:
        return text, ''
    return parts[0].strip(), parts[1].strip()


def pair_nutrition_rows(label_rows, value_rows):
    paired_lines = []
    for index, label in enumerate(label_rows):
        if index >= len(value_rows):
            break
        paired_lines.append('%s %s'%(label, value_rows[index]))
    return '\n'.join(paired_lines)


def getNutritionParts(food,height):
    section_lines = []
    for line in food:
        try:
            line_height = float(line.get('height', 0))
            line_width = float(line.get('width', 0))
        except (TypeError, ValueError):
            continue

        if line_height < float(height) - 260 or line_height > float(height) + 260:
            continue

        text = str(line.get('text', '') or '').strip()
        if not text:
            continue

        section_lines.append({
            'height': line_height,
            'width': line_width,
            'text': text,
        })

    if not section_lines:
        return {'main': '', 'side': ''}

    anchors = [line for line in section_lines if re.search(r'Nutritional\s+Information', line['text'], flags=re.IGNORECASE)]
    if not anchors:
        return {'main': '', 'side': ''}

    anchor = min(anchors, key=lambda item: abs(item['height'] - float(height)))
    label_rows = []
    value_candidates = []

    for line in section_lines:
        if line['height'] > anchor['height'] + 20 or line['height'] < anchor['height'] - 170:
            continue

        text = line['text']
        if re.search(r'Nutritional\s+Information', text, flags=re.IGNORECASE):
            continue

        parts = [part.strip() for part in text.split('\n') if part and part.strip()]
        if not parts:
            continue

        if line['width'] <= 110 and any(re.search(r'Servings|Calories|Protein|Carb|Fiber|Fat|Sodium|Sug', part, flags=re.IGNORECASE) for part in parts):
            label_rows.extend(parts)
            continue

        numeric_parts = [part for part in parts if re.match(r'^[0-9]+(?:\.[0-9]+)?$', part)]
        if len(numeric_parts) >= 4:
            value_candidates.append({
                'height': line['height'],
                'width': line['width'],
                'numeric': numeric_parts,
                'has_main_marker': bool(re.search(r'(^|\n)Main\b', text, flags=re.IGNORECASE)),
                'has_side_marker': bool(re.search(r'(^|\n)Side\b', text, flags=re.IGNORECASE)),
            })

    if not label_rows or not value_candidates:
        fallback_lines = []
        for line in section_lines:
            if line['height'] > anchor['height'] + 20 or line['height'] < anchor['height'] - 170:
                continue
            if line['width'] <= 200:
                fallback_lines.append(re.sub('\n+', ' ', line['text']).strip())

        fallback_text = '\n'.join(fallback_lines)
        if fallback_text:
            pdf_logger.info('Nutrition text candidates found near meal height %s: %s', height, len(fallback_lines))
            pdf_logger.debug('Nutrition fallback text: %s', fallback_text)
        return {'main': fallback_text, 'side': ''}

    sorted_candidates = sorted(value_candidates, key=lambda candidate: (abs(candidate['height'] - anchor['height']), candidate['width']))
    main_candidate = None
    side_candidate = None

    main_marked = [candidate for candidate in sorted_candidates if candidate['has_main_marker']]
    side_marked = [candidate for candidate in sorted_candidates if candidate['has_side_marker']]

    if main_marked:
        main_candidate = min(main_marked, key=lambda candidate: (abs(candidate['height'] - anchor['height']), candidate['width']))
    else:
        main_candidate = sorted(sorted_candidates, key=lambda candidate: (abs(candidate['height'] - anchor['height']), candidate['width']))[0]

    if side_marked:
        side_candidate = min(side_marked, key=lambda candidate: (abs(candidate['height'] - anchor['height']), abs(candidate['width'] - (main_candidate['width'] + 35))))
    else:
        right_side = [candidate for candidate in sorted_candidates if candidate['width'] > main_candidate['width'] + 15]
        if right_side:
            side_candidate = sorted(right_side, key=lambda candidate: (abs(candidate['height'] - anchor['height']), candidate['width']))[0]

    main_text = pair_nutrition_rows(label_rows, main_candidate['numeric']) if main_candidate else ''
    side_text = pair_nutrition_rows(label_rows, side_candidate['numeric']) if side_candidate else ''

    pdf_logger.info('Nutrition text candidates found near meal height %s: labels=%s values=%s', height, len(label_rows), len(value_candidates))
    pdf_logger.debug('Nutrition main text: %s', main_text)
    if side_text:
        pdf_logger.debug('Nutrition side text: %s', side_text)

    return {
        'main': main_text,
        'side': side_text,
    }


def getNutrition(food,height):
    return getNutritionParts(food,height).get('main', '')

'''
Take the times and identify them.
if cook and total times are pieced into one then seperate them
    this function was is to fix an issue where you get
    Cook\nTotal\nXh Xm Xh Xm
    instead of indivitual times
'''
def getTimes(prep,cook,total,height):
    thisTotal=' \n '
    thisCook=' \n '
    thisPrep=' \n '

    pdf_logger.info('Getting the times')
    '''locate times if we have them'''
    for each in prep:
        if int(each['height']) in range(int(height)-140,int(height)):
            thisPrep = each['text']
            pdf_logger.debug(thisPrep)
    for each in cook:
        if int(each['height']) in range(int(height)-140,int(height)):
            thisCook = each['text']
            pdf_logger.debug(thisCook)
    for each in total:
        if int(each['height']) in range(int(height)-140,int(height)):
            thisTotal = each['text']
            pdf_logger.debug(thisTotal)

    '''Does thisCook contain to times? if so fix it'''
    try:
        thisCook
    except NameError:
        pdf_logger.info('thisCook not set: total is %s, prep is %s'%(thisTotal,thisPrep))
        if ('Cook\n' in thisTotal and 'Total\n' in thisTotal):
            pdf_logger.info('thisTotal has both cook and total, splitting itmes')
            thisCook,thisTotal=splitTimes(thisTotal)
    else:
        if ('Cook\n' in thisCook and 'Total\n' in thisCook):
            pdf_logger.info('thisCook has both cook and total, splitting itmes')
            thisCook,thisTotal=splitTimes(thisCook)

    prep_value = extract_time_line(thisPrep)
    cook_value = extract_time_line(thisCook)
    total_value = extract_time_line(thisTotal)

    cook_values = extract_time_values(thisCook)
    total_values = extract_time_values(thisTotal)

    if len(cook_values) >= 2 and not total_value:
        cook_value = cook_values[0]
        total_value = cook_values[1]
    elif cook_values and not cook_value:
        cook_value = cook_values[0]

    if total_values and not total_value:
        total_value = total_values[0]

    if not total_value and prep_value and cook_value:
        prep_minutes = time_text_to_minutes(prep_value)
        cook_minutes = time_text_to_minutes(cook_value)
        if prep_minutes is not None and cook_minutes is not None:
            total_value = minutes_to_time_value(prep_minutes + cook_minutes)

    return prep_value, cook_value, total_value

def splitTimes(thisCook):
        pieces = thisCook.split('\n')
        timeParts = pieces[2].split(' ')
        timea= ''
        timeb = ''
        partsCount = len(timeParts)
        for count,part in enumerate(timeParts):
            if count < (partsCount/2):
                timea = timea + part + ' '
            elif count >= (partsCount/2):
                timeb = timeb + part + ' '
        thisCook = 'Cook\n'+timea+'\n'
        thisTotal = 'Total\n'+timeb+'\n'
        return thisCook,thisTotal

'''this function takes the data pull out of the pdf and assembles the meals togeather for a page'''
def mealAssembly(data):
    meals = []

    '''user the meal number list to itereate over the others since every meal SHOULD have one, and they ara easy to detect'''
    for count,mealNum in enumerate(data['mealNum']):
        meal ={}
        meal['number'] = mealNum['text'].strip()
        pdf_logger.debug('Meal number: %s'%(mealNum))
        meal['mainDish'],meal['sideDish'],meal['type'] = getDishes(data['food'],mealNum['height'],meal['number'])
        meal['prep'],meal['cook'],meal['total'] = getTimes(data['prep'],data['cook'],data['total'],mealNum['height'])
        meal['ingredients'],meal['instructions'] = getSteps(data['food'],mealNum['height'])
        meal['ingredientsMain'],meal['ingredientsSide'] = split_dual_section_text(meal.get('ingredients', ''))
        meal['instructionsMain'],meal['instructionsSide'] = split_dual_section_text(meal.get('instructions', ''))

        nutrition_parts = getNutritionParts(data['food'],mealNum['height'])
        meal['nutritionTextMain'] = nutrition_parts.get('main', '')
        meal['nutritionTextSide'] = nutrition_parts.get('side', '')
        meal['nutritionText'] = meal['nutritionTextMain']
        if meal['nutritionTextMain']:
            pdf_logger.info('Nutrition text for meal %s (%s): %s', meal['number'], meal['mainDish'], meal['nutritionTextMain'])
        if meal['nutritionTextSide']:
            pdf_logger.info('Nutrition side text for meal %s (%s): %s', meal['number'], meal['sideDish'], meal['nutritionTextSide'])
        meals.append(meal)
    if debug == 'pdf':
        print(meals)
    return meals

'''
this function takes a pdf and pulls the data and returns the full set of meals for the pdf
'''
def getMeals(pdf,meal_type):
    meals = []
    pdf_logger.info('setting up the paramaters for pdfminer')
    ''' Set parameters for pdf analysis.'''
    laparams = LAParams()
    rsrcmgr = PDFResourceManager()
    fp = open(pdf, 'rb')
    parser = PDFParser(fp)
    document = PDFDocument(parser)

    pdf_logger.info('creating a PDF page aggregator object')
    ''' Create a PDF page aggregator object.'''
    device = PDFPageAggregator(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    pages = list(enumerate(PDFPage.create_pages(document)))
    pageCount=1
    totalPages = len(pages)

    '''process each page'''
    for pageNumber,page in pages:
        pdf_logger.info('processing page %s of %s'%(pageNumber,totalPages))
        '''is it the last page? if so bail, its the shopping list'''
        pdf_logger.info('meals found so far: %s'%(len(meals)))
        if pageCount == totalPages or len(meals) >= 8:
            pdf_logger.debug('last page or 7 meals found')
            break

        data = {}
        data['mealNum'] = []
        data['mealType'] = []
        data['food'] = []
        data['prep'] = []
        data['cook'] = []
        data['total'] = []

        interpreter.process_page(page)
        # receive the LTPage object for the page.
        layout = device.get_result()
        pageList = []

        ''' go through everything, only grabbing the text'''
        for objType in layout:
            objDict = {}
            if (isinstance(objType, pdfminer.layout.LTTextBoxHorizontal)):
                 objDict['height'] = objType.y1
                 objDict['width'] = objType.x0
                 objDict['text'] = objType.get_text()
                 pageList.append(objDict)

        if str(meal_type or '').strip().lower() == 'recipe':
            staples_marker = any(re.search(r'No\s+staples\s+for\s+this\s+meal', str(item.get('text', '')), flags=re.IGNORECASE) for item in pageList)
            if staples_marker:
                pdf_logger.info('Detected staples page marker; stopping recipe parsing before staples section')
                break

        '''
        take a best guess at the contect of each text block
        break like types into seperate pieces
        Performance help:parser_
           put everything but meal number into one list.
           create dictionary of meals with meal number hieght as key
           identify and sort everything at that level
        '''
        pdf_logger.info('sorting the data')
        for item in pageList:
            if 'Prep\n' in item['text']:
                data['prep'].append(item)
            elif re.search('^Cook\n',item['text']):
                data['cook'].append(item)
            elif 'Total\n' in item['text']:
                data['total'].append(item)

            #elif '----' in item['text']:
            #    data['ingdir'].append(item)
            elif 'Meals: Side dishes are in ITALICS\n' in item['text']:
                continue
            elif 'Grocery Items to Purchase' in item['text']:
                break #this is the last page :\
            elif re.search(r'^%s \d'%(meal_type),item['text']):
                data['mealNum'].append(item)
            else:
                data['food'].append(item)
        pdf_logger.debug(data)
        pdf_logger.info('assembling the meals from this page')
        meals = meals + mealAssembly(data)
        pageCount += 1
    return meals

'''
prepare the data for smartsheet.
Here the columnId and meal dictionary keys need to match
this stiches everything together to build the smartsheet rows with parentId
'''
def prepData(meals, rowID, columnIds):
    ssdata = []
    for meal in meals:
        row = {}
        row['parentId'] = rowID
        row['cells'] = []
        for item in meal:
            if item not in columnIds:
                continue
            columns ={}
            columns['columnId'] = columnIds[item]
            columns['value'] = meal[item]
            row['cells'].append(columns)
        ssdata.append(row)
    return ssdata


'''
Main loop
'''
if __name__ == '__main__':
    parser_logger.info('Starting')
    bail = False
    debug = 'depreicated'

    load_dotenv()
    parser_logger.info('Reading in Config')
    sheetID = os.getenv("sheetID") #Req
    ssToken = os.getenv("ssToken") #Req
    server  = os.getenv("server")
    countLimit = os.getenv("countLimit")
    parser_debug = os.getenv("parser_debug")
    smartsheet_debug = os.getenv("smartsheet_debug")
    pdf_debug = os.getenv("pdf_debug")
    smartsheetDown = os.getenv("smartsheetDown") 
    smartsheetUp = os.getenv("smartsheetUp")
    mealieUp = os.getenv("mealieUp")
    mealie_parse_ingredients_setting = os.getenv("mealie_parse_ingredients")
    mealie_url = normalize_mealie_url(os.getenv("mealie_url"))
    mealie_api_token = os.getenv("mealie_api_token")
    meal_type = os.getenv("meal_type")
    meal_heading = os.getenv("meal_heading") or meal_type

    sslVerify = os.getenv("sslVerify")

    parser_logger.info('Setting levels for Logging')

    log_levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }

    parser_log_level = log_levels.get(parser_debug, logging.INFO)
    parser_logger.setLevel(parser_log_level)

    if True:

        smartsheet_logger.info('Setting levels for Logging')
        smartsheet_log_level = log_levels.get(smartsheet_debug, logging.INFO)
        smartsheet_logger.setLevel(smartsheet_log_level)

        pdf_logger.info('Setting levels for Logging')
        pdf_log_level = log_levels.get(pdf_debug, logging.INFO)
        pdf_logger.setLevel(pdf_log_level)

        if sslVerify == 'True':
            sslVerify=True
        else:
            sslVerify=False

        smartsheet_upload_enabled = parse_bool(smartsheetUp, True)
        mealie_upload_enabled = parse_bool(mealieUp, False)
        mealie_ingredient_nlp_enabled = parse_bool(mealie_parse_ingredients_setting, False)

    if not sheetID:
      parser_logger.error("Please Provide a Sheet ID")
      bail=True

    if not ssToken:
      parser_logger.error("Please Provide a Smartsheet API token")
      bail=True

    if bail:
      sys.exit("Missing Required Variables")

    '''bring in config'''
    #exec(compile(open("menuParser.conf").read(), "menuParser.conf", 'exec'), locals())

    headers = {'Authorization': 'Bearer '+str(ssToken)}

    mealie_headers = {
        'Authorization': 'Bearer '+str(mealie_api_token),
        'Content-Type': 'application/json'
    }

    if mealie_upload_enabled and not mealie_url:
        parser_logger.error('mealieUp=True but mealie_url is missing')
        bail = True

    if mealie_upload_enabled and not mealie_api_token:
        parser_logger.error('mealieUp=True but mealie_api_token is missing')
        bail = True

    if mealie_upload_enabled and not bail:
        if not mealie_preflight_check():
            parser_logger.error('mealieUp=True but Mealie API preflight check failed for mealie_url=%s', mealie_url)
            bail = True

    if bail:
        sys.exit("Missing Required Variables")

    '''get sheet data'''
    sheet = getSheet(sheetID)
    #if debug == 'smartsheet':
    smartsheet_logger.debug(sheet)

    '''build list of columns'''
    columnId = getColumns(sheet)
    #if debug == 'smartsheet':
    smartsheet_logger.debug(columnId)

    '''Get list of attachments'''
    attachments = getAttachments(sheetID)
    #if debug == 'smartsheet':
    smartsheet_logger.debug(attachments)

    rows = []
    child_row_parent_ids = set()
    count = 0

    for each in sheet['rows']:
        parent_id = each.get('parentId')
        if parent_id:
            child_row_parent_ids.add(parent_id)

    '''see if the row needs to be processed'''
    for each in sheet['rows']:
        for cell in each['cells']:
            if (cell['columnId'] == columnId['process']):
                try:
                    if (cell['value'] == True):
                        rows.append(each['id'])
                except KeyError:
                    continue
    #if debug == 'smartsheet':
    smartsheet_logger.debug(rows)

    '''
    Performance Help:
       Run through the list of rows to be processed and select out only the needed attachments?
    '''
    '''run through all sheet attacments'''
    attachments = sorted(attachments['data'],key=itemgetter('parentId'))
    rows = sorted(rows)
    a = 0
    count = 0
    for row in rows:
        found = False
        if a < len(attachments):
            while attachments[a]['parentId'] <= row:
                if attachments[a]['parentId'] == row and attachments[a]['parentType'] == 'ROW':
                    found = True
                    count += 1 #debug
                    attachment_name = attachments[a].get('name', 'unknown-plan.pdf')
                    if smartsheetDown == 'True':
                        '''get attachment url and download the pdf'''
                        attachmentObj = getAttachment(sheetID,attachments[a]['id'])
                        attachment_name = attachmentObj.get('name', attachment_name)
                        fh = urllib.request.urlopen(attachmentObj['url'])
                        localfile = open('tmp.pdf','wb')
                        localfile.write(fh.read())
                        localfile.close()
                    '''process the PDF and get the meals back'''
                    try:
                        meals = getMeals('tmp.pdf',meal_heading)
                    except:
                        parser_logger.critical(("Failed: "+ str(row)))
                        parser_logger.critical((traceback.print_exc()))
                        break
                    if pdf_debug == 'debug':
                        pdf_logger.debug(attachment_name)
                        for meal in meals:
                            pdf_logger.debug("New Meal")
                            for part in meal:
                                pdf_logger.debug(part + ': ' + meal[part])

                    parent_has_children = attachments[a]['parentId'] in child_row_parent_ids
                    smartsheet_success = True
                    mealie_success = True

                    if smartsheet_upload_enabled and not parent_has_children:
                        '''get the dictionary ready for smartsheet'''
                        ssdata = prepData(meals, attachments[a]['parentId'],columnId)
                        result = insertRows(sheetID,ssdata)
                        if debug == 'requests':
                            print(result)
                        if result.get('resultCode') != 0:
                            smartsheet_success = False
                            smartsheet_logger.error('Failed inserting child rows for parent %s: %s', attachments[a]['parentId'], result)
                    elif smartsheet_upload_enabled and parent_has_children:
                        parser_logger.info('Parent row %s already has child rows, skipping Smartsheet insert and syncing only other targets', attachments[a]['parentId'])
                    elif not smartsheet_upload_enabled:
                        parser_logger.info('Smartsheet upload disabled, skipping Smartsheet insert for parent %s and syncing only other targets', attachments[a]['parentId'])
                        smartsheet_success = False

                    if mealie_upload_enabled:
                        mealie_success = upload_meals_to_mealie(meals, meal_type, attachment_name, attachments[a]['parentId'], 'tmp.pdf', attachment_name)

                    any_upload_target = smartsheet_upload_enabled or mealie_upload_enabled
                    if any_upload_target and smartsheet_success and mealie_success:
                        '''prepare to uncheck the box so it doesn't get reprocessed'''
                        checkData = {"id":attachments[a]['parentId'],"cells":[{"columnId":columnId['process'], "value":False}]}
                        updateRow(sheetID,attachments[a]['parentId'],checkData)
                    '''Stop after only some menus?'''
                    if countLimit == 'True':
                        if count > 0:
                            exit()
                a += 1
                if a>= len(attachments):
                    break
        if found == False:
            parser_logger.info("No Attachment found for row: "+ str(row))