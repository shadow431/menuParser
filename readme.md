<h3>Install and Run</h3>
  docker build -t menuparser .
  docker run --rm -e sheetID='<your_sheet_id>' -e ssToken='<your_smartsheet_api_token>' menuparser:latest

<h3>menuPaser Environemnt Vairable options</h3>
  **sheetID** -- Requried
      This is the sheetID were it will grab the attachments, and upload the parsed data
  
  **ssToken** -- Required
      This will be your smartsheet API token

  **server** -- Defaults to Prod
      This is the host portion of the URL to send Smartsheet Requests to
  
  **countLimit**
      activates a count in the row attachment processor to force a premeture completion after x menues
  
  **debug**
      use for see the data at various steps.
      Current options are 'pdf, smartsheet, approve, requests'
        pdf: prints out the data as it is pulled and manaipulated,
        smartsheet: prints the data as it is retrieved, prepared, and submited for/to smartsheet,
        approve: itterates through each component of the menus so you can see if it is parsing right.
        requests: prints out the response from smartsheet for row inserts
  
  **smartsheetDown**
      Boolean used to set whether to pull data from smartsheet for processing
      if False it will download the sheet and process the row/attachemnt info, but will use the existing pdf document.
      Note: if Flase I recommend setting countLimit = True
  
  **smartsheetUP**
      Boolean used to set whether or not to upload the data once processed back up to smartsheet

<h2>Optimization test</h2>
Original
Fri Apr 17 08:31:31 PDT 2015
Fri Apr 17 08:34:42 PDT 2015


Test 1 - New Attacment processing
Fri Apr 17 08:35:51 PDT 2015
Fri Apr 17 08:39:10 PDT 2015
