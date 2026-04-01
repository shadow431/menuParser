<h3>Install and Run</h3>
  docker build -t menuparser .
  docker run --rm -e sheetID='<your_sheet_id>' -e ssToken='<your_smartsheet_api_token>' -e meal_type='<Meal>|<Dessert>|<Recipe>' menuparser:latest

  docker run --rm --env-file .env --env-file .env-desserts menuparser:latest
  docker run --rm --env-file .env --env-file .env-desserts menuparser:latest
  docker run --rm --env-file .env --env-file .env-occasions menuparser:latest

  Run with pdf debuging and not uploading to smartsheet after
  docker run --rm --env-file .env -e pdf_debug=debug -e smartsheetUp=False menuparser:latest

<h3>Smartsheet Recipe HTML Viewer</h3>

  Quick container that reads recipe rows directly from Smartsheet and serves HTML pages (one recipe per page).

  Run with compose (using your existing env files for `ssToken` + `sheetID`):

      docker compose --env-file .env --env-file .env-meals up -d --build smartsheet-viewer

  Open:

      http://localhost:8088

  Notes:
  - Index page lists recipes.
  - Each recipe links to `/recipe/<rowId>`.
  - This reads Smartsheet live on each request.
    - If Mealie URL import rejects the domain (`InvalidDomainError`), open a recipe page
        and use **Import This Recipe to Mealie**. This uses Mealie `create/html-or-json`
        and bypasses domain restrictions.

<h3>Run Mealie Locally with Docker Compose</h3>

  Files added for Mealie:
  - compose.mealie.yml
  - compose.mealie.nfs.yml
  - mealie.env.sample

  Recommended default is local Docker volumes with PostgreSQL:

  1. Copy mealie.env.sample to .env.mealie and adjust values
  2. Start Mealie locally:
      docker compose --env-file .env.mealie -f compose.mealie.yml up -d
  3. Open Mealie at the URL defined by MEALIE_BASE_URL (default http://localhost:9925)

  Optional NFS-backed storage:

      docker compose --env-file .env.mealie -f compose.mealie.yml -f compose.mealie.nfs.yml up -d

  Notes:
  - This stack uses PostgreSQL because Mealie docs warn against SQLite on NAS/NFS.
  - Local volumes are the safest default.
  - NFS is available as an override, but live PostgreSQL data on NFS can be less reliable than local disk.
     Best practice is local runtime storage plus backups exported to NFS.

<h3>menuPaser Environemnt Vairable options</h3>

  **sheetID** -- Requried
      This is the sheetID were it will grab the attachments, and upload the parsed data
  
  **ssToken** -- Required
      This will be your smartsheet API token

  **server** -- Defaults to Prod
      This is the host portion of the URL to send Smartsheet Requests to
  
  **countLimit**
      activates a count in the row attachment processor to force a premeture completion after x menues
  
  **debug** DEPRICATED see other debug options
      use for see the data at various steps.
      Current options are 'pdf, smartsheet, approve, requests'
        pdf: prints out the data as it is pulled and manaipulated,
        smartsheet: prints the data as it is retrieved, prepared, and submited for/to smartsheet,
        approve: itterates through each component of the menus so you can see if it is parsing right.
        requests: prints out the response from smartsheet for row inserts

  **smartsheet_debug**
  **pdf_debug**
  **parser_debug**
     these three set the Logging level for different parts of the process
     Smartsheet changes logging level related to smartsheet communications
     pdf change logging level related to parsing and process of the pdf
     parser changes logging level for anything else

  **smartsheetDown**
      Boolean used to set whether to pull data from smartsheet for processing
      if False it will download the sheet and process the row/attachemnt info, but will use the existing pdf document.
      Note: if Flase I recommend setting countLimit = True
  
  **smartsheetUP**
      Boolean used to set whether or not to upload the data once processed back up to smartsheet
      If True and the selected parent row already has child rows, the parser will skip Smartsheet insert
      and continue with other enabled upload targets (for example Mealie).

  **mealieUp**
      Boolean used to set whether recipes are uploaded to Mealie via API

  **mealie_url**
      Base URL for your Mealie instance (example: https://mealie.example.com)

  **mealie_api_token**
      Long-lived API token created in Mealie user profile

  When Mealie upload is enabled, each recipe is created/updated with `extras` metadata including
  the source meal plan filename, meal number/type, and source Smartsheet row ID.

  **sslVerify**
      Boolean used to set whether or not to verify SSL certs for Smartsheet

  **meal_type**
      String of one of '<Meal>|<Dessert>|<Recipe>'
      This will allow processing of different meal types


<h3>TODO</h3>
better error handling when entering incorrect sheetID/Token/api enpoint
get running in lamdba
add webhook
only proccess row that triggered webhook?? otherwise look for rows marked for processing?
