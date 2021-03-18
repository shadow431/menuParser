from pdfminer.layout import LAParams
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfparser import PDFParser
import pdfminer
from operator import itemgetter
from dotenv import load_dotenv
import re, json, requests, urllib.request, urllib.error, urllib.parse,traceback, os

'''
get the smartsheet data
TODO: replace with sdk
'''
def getSheet(sheetID):
    url = 'https://%s/2.0/sheets/%s'%(server,sheetID)
    r = requests.get(url, headers=headers)
    rArr = r.json()
    return rArr

def getAttachments(sheetID):
    url = 'https://%s/2.0/sheets/%s/attachments?includeAll=True'%(server,sheetID)
    r = requests.get(url, headers=headers)
    rArr = r.json()
    return rArr

def getAttachment(sheetID,attachmentID):
    url = 'https://%s/2.0/sheets/%s/attachments/%s'%(server,sheetID,attachmentID)
    r = requests.get(url, headers=headers)
    rArr = r.json()
    return rArr

def insertRows(sheetId,data):
    jsonData = json.dumps(data)
    url = 'https://%s/2.0/sheets/%s/rows'%(server,sheetID)
    r = requests.post(url, data=jsonData, headers=headers)
    return r.json()

def updateRow(sheetId,rowId,data):
    data = json.dumps(data)
    url = 'https://%s/2.0/sheets/%s/rows'%(server,sheetID)
    r = requests.put(url, data=data, headers=headers)
    return r


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
def getDishes(food,height):
    if debug == 'pdf': print(height)

    menuLine =[]
    menuType = ''

    '''Get the lines pertaining to this meail'''
    for line in food:
        if debug == 'pdf': print(line)
        if int(line['height']) in range(int(height)-100,int(height)):
            menuLine.append(line)
        elif int(line['height']) in range(int(height),int(height)+3) and line['width'] < 193.0:
            menuType = line['text']

    '''
    for each line, if it is the first one, assume it is the start of the main dish name
    otherwise, check the hieght compare to the first line, it is either a second line of a dish name,
    or the first of the side dish name.  if it side dish has been set it is probably the second line of that
    '''
    for num,each in enumerate(menuLine):
        if debug == 'pdf': print((str(num) + ' : ' + str(each)))
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

    if debug == 'pdf': eval(input('Press Enter to Continue'))

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

    return mainDish,sideDish,menuType

'''
This function takes the ingrediends and the directions, gets the ones for the selected meal,
 and identifies the ingredients and directions secitons for use
'''
def getSteps(ingdir,height):
    items=[]

    '''find the pieces'''
    for item in ingdir:
        if int(item['height']) in range(int(height),int(height)+20) and (item['width'] == 193.0 or item['width'] == 389.0):
           if debug == 'pdf':
               print(height)
               print(item)
               eval(input("Press any key to continue"))
           items.append(item)

    '''sort them by horizontal alignment'''
    items = sorted(items,key=itemgetter('width'))

    '''remove the words Ingredients and Instructions for the first meal on each page'''
    if items[0]['text'].startswith('Ingredients:\n'):
        items[0]['text'] = items[0]['text'][13:len(items[0]['text'])]
    if items[1]['text'].startswith('Instructions:\n'):
        items[1]['text'] = items[1]['text'][15:len(items[1]['text'])]

    return items[0]['text'].strip(),items[1]['text'].strip()

'''
Take the times and identify them.
if cook and total times are pieced into one then seperate them
    this function was is to fix an issue where you get
    Cook\nTotal\nXh Xm Xh Xm
    instead of indivitual times
'''
def getTimes(prep,cook,total,height):
    thisTotal=''

    '''locate times if we have them'''
    for each in prep:
        if int(each['height']) in range(int(height)-140,int(height)):
            thisPrep = each['text']
    for each in cook:
        if int(each['height']) in range(int(height)-140,int(height)):
            thisCook = each['text']
    for each in total:
        if int(each['height']) in range(int(height)-140,int(height)):
            thisTotal = each['text']

    '''Does thisCook contain to times? if so fix it'''
    try:
        thisCook
    except NameError:
        print(thisTotal)
        print(thisPrep)
        if ('Cook\n' in thisTotal and 'Total\n' in thisTotal):
            thisCook,thisTotal=splitTimes(thisTotal)
    else:
        if ('Cook\n' in thisCook and 'Total\n' in thisCook):
            thisCook,thisTotal=splitTimes(thisCook)

    '''Return the times, but only the hours and minutes, we no longer need the words'''
    return thisPrep.split('\n')[1],thisCook.split('\n')[1],thisTotal.split('\n')[1]

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
        meal['mainDish'],meal['sideDish'],meal['type'] = getDishes(data['food'],mealNum['height'])
        meal['prep'],meal['cook'],meal['total'] = getTimes(data['prep'],data['cook'],data['total'],mealNum['height'])
        meal['ingredients'],meal['instructions'] = getSteps(data['food'],mealNum['height'])
        meals.append(meal)
    if debug == 'pdf':
        print(meals)
        eval(input("press enter to continue..."))
    return meals

'''
this function takes a pdf and pulls the data and returns the full set of meals for the pdf
'''
def getMeals(pdf):
    meals = []

    ''' Set parameters for pdf analysis.'''
    laparams = LAParams()
    rsrcmgr = PDFResourceManager()
    fp = open(pdf, 'rb')
    parser = PDFParser(fp)
    document = PDFDocument(parser)

    ''' Create a PDF page aggregator object.'''
    device = PDFPageAggregator(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    pages = list(enumerate(PDFPage.create_pages(document)))
    pageCount=1
    totalPages = len(pages)

    '''process each page'''
    for pageNumber,page in pages:
        '''is it the last page? if so bail, its the shopping list'''
        if pageCount == totalPages or len(meals) == 7:
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

        '''
        take a best guess at the contect of each text block
        break like types into seperate pieces
        Performance help:
           put everything but meal number into one list.
           create dictionary of meals with meal number hieght as key
           identify and sort everything at that level
        '''
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
            elif re.search('^Meal \d',item['text']):
                data['mealNum'].append(item)
            else:
                data['food'].append(item)
        if debug == 'pdf':
            print(data)
            eval(input('Press any key to continue....'))
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
    load_dotenv()

    sheetID = os.getenv("sheetID")
    ssToken = os.getenv("ssToken")
    server  = os.getenv("server")
    countLimit = os.getenv("countLimit")
    debug = os.getenv("debug")
    smartsheetDown = os.getenv("smartsheetDown") 
    smartsheetUp = os.getenv("smartsheetUp")


    '''bring in config'''
    #exec(compile(open("menuParser.conf").read(), "menuParser.conf", 'exec'), locals())

    headers = {'Authorization': 'Bearer '+str(ssToken)}

    '''get sheet data'''
    sheet = getSheet(sheetID)
    if debug == 'smartsheet':
        print(sheet)
        eval(input("Press Enter to continue..."))

    '''build list of columns'''
    columnId = getColumns(sheet)
    if debug == 'smartsheet':
        print(columnId)
        eval(input("Press Enter to continue..."))

    '''Get list of attachments'''
    attachments = getAttachments(sheetID)
    if debug == 'smartsheet':
        print(attachments)
        eval(input("Press Enter to continue..."))

    rows = []
    count = 0

    '''see if the row needs to be processed'''
    for each in sheet['rows']:
        for cell in each['cells']:
            if (cell['columnId'] == columnId['process']):
                try:
                    if (cell['value'] == True):
                        rows.append(each['id'])
                except KeyError:
                    continue
    if debug == 'smartsheet':
        print(rows)
        eval(input("Press Enter to continue..."))
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
                    if smartsheetDown == 'True':
                        '''get attachment url and download the pdf'''
                        attachmentObj = getAttachment(sheetID,attachments[a]['id'])
                        fh = urllib.request.urlopen(attachmentObj['url'])
                        localfile = open('tmp.pdf','w')
                        localfile.write(fh.read())
                        localfile.close()
                    '''process the PDF and get the meals back'''
                    try:
                        meals = getMeals('tmp.pdf')
                    except:
                        print(("Failed: "+ str(row)))
                        print((traceback.print_exc()))
                        break
                    if debug == 'approve':
                        print((attachment['name']))
                        for meal in meals:
                            print("New Meal")
                            for part in meal:
                                print((part + ': ' + meal[part]))
                                eval(input("Press Enter For Next"))
                    '''get the dictionary ready for smartsheet'''
                    ssdata = prepData(meals, attachments[a]['parentId'],columnId)
                    '''prepare to uncheck the box so it doesn't get reprocessed'''
                    checkData = {"id":attachments[a]['parentId'],"cells":[{"columnId":columnId['process'], "value":False}]}
                    if smartsheetUp == 'True':
                        '''upload the data'''
                        result = insertRows(sheetID,ssdata)
                        '''if the save succeded uncheck the processing box'''
                        if debug == 'requests':
                            print(result)
                        if result['resultCode'] == 0:
                            updateRow(sheetID,attachments[a]['parentId'],checkData)
                    '''Stop after only some menus?'''
                    if countLimit == 'True':
                        if count > 0:
                            exit()
                a += 1
                if a>= len(attachments):
                    break
        if found == False:
            print("ERROR")
