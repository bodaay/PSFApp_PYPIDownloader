import os
import sys
import sqlite3
import requests
import shutil
import hashlib
import json
import time
import signal
import base64
import codecs
import math
import urllib.parse
import html as htmlescape # I don't want to get mixed up with below lxml
from datetime import datetime
# I'm using thead pool, because its easier and I can use global variables easily with it, We don't need high processing power for this project, just multi thread
from multiprocessing.pool import Pool
from multiprocessing import Queue
from lxml import html# pip install lxml
from termcolor import colored
from zipfile import ZipFile 
from pkg_resources import parse_version
import tqdm  # pip3 install tqdm
import re
 
BatchSize = 30
MaxDownloadProcess = 50
MaxNumberOfDownloadRetries = 2
BackupProgeressAfterBatches = 5
DONWLOAD_CHUNK_SIZE_MB = 4
SkipDownloadingListFile=True
ROOT_FOLDER_NAME = "/Synology/PYPI/"
MAIN_Packages_List_Link = "https://pypi.org/simple/"
JSON_Info_Link_Prefix = "https://pypi.org/pypi/"

"""
I'll follow this folder structure

ROOT
    - simple
        - package-name
            - binaries
            - json
              - index.json
            - __lastserial
            - index.html
    - sync_data_indexes
        - logs
            - FailedList_%d-%m-%Y_%H_%M.log
        - __progress.json
        - __blacklist
"""

working_path = os.path.join(ROOT_FOLDER_NAME,"sync_data_indexes")
packages_data_path = os.path.join(ROOT_FOLDER_NAME, "simple")
logfile_path = os.path.join(working_path, "logs")
JSON_progress_data_file = os.path.join(working_path,"__progress.json")
BlackListFile = os.path.join(working_path,"__blacklist")
logFileName = os.path.join(logfile_path,datetime.now().strftime('FailedList_%d-%m-%Y_%H_%M.log'))


base_scirpt_path = os.path.dirname(os.path.realpath(__file__))


MAIN_INDEX_HTML_TEMPLATE="""<!DOCTYPE html>
<html>
  <head>
    <title>Simple Index</title>
  </head>
  <body>
@@@LINKS@@@
  </body>
</html>"""


INDEX_HTML_TEMPLATE="""<!DOCTYPE html>
<html>
  <head>
    <title>Links for @@@PACKAGE_NAME@@@</title>
  </head>
  <body>
    <h1>Links for @@@PACKAGE_NAME@@@</h1>
@@@LINKS@@@
  </body>
</html>
<!--SERIAL @@@SERIAL@@@-->"""

INDEX_HTML_LINKS_TEMPLATE="""\t\t\t<a href="@@@FILE_URL@@@" @@@EXTRAS@@@ >@@@FILE_NAME@@@</a><br/>"""

def GetMD5(file1):
    if not os.path.exists(file1):
        return None
    hashed = hashlib.md5()
    with open(file1, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def GetSHA512(file1):
    if not os.path.exists(file1):
        return None
    hashed = hashlib.sha512()
    with open(file1, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def GetSHA256(file1):
    if not os.path.exists(file1):
        return None
    hashed = hashlib.sha256()
    with open(file1, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def ChechHash(hashfunction, file):
    if hashfunction.lower() == "sha512":
        return GetSHA512(file)
    if hashfunction.lower() == "sha256":
        return GetSHA512(file)
    if hashfunction.lower() == "md5":
        return GetSHA512(file)
def humanbytes(B):
   'Return the given bytes as a human friendly KB, MB, GB, or TB string'
   B = float(B)
   KB = float(1024)
   MB = float(KB ** 2) # 1,048,576
   GB = float(KB ** 3) # 1,073,741,824
   TB = float(KB ** 4) # 1,099,511,627,776
   if B < KB:
      return '{0} {1}'.format(B,'Bytes' if 0 == B > 1 else 'Byte')
   elif KB <= B < MB:
      return '{0:.2f} KB'.format(B/KB)
   elif MB <= B < GB:
      return '{0:.2f} MB'.format(B/MB)
   elif GB <= B < TB:
      return '{0:.2f} GB'.format(B/GB)
   elif TB <= B:
      return '{0:.2f} TB'.format(B/TB)

def FilesMatching(file1, file2):
    # first we check by size, faster
    if not os.path.exists(file1):
        return False
    if not os.path.exists(file2):
        return False
    if os.stat(file1).st_size != os.stat(file2).st_size:
        return False
    if GetMD5(file1) != GetMD5(file2):
        return False
    # then we check by checksum
    return True



def WriteProgressJSON(jsondata,saveBackup=True):
    if saveBackup:
        if os.path.exists(JSON_progress_data_file):
            backupPath = os.path.join(working_path,"backup")
            os.makedirs(backupPath,exist_ok=True)
            newFileName= os.path.join(backupPath,"__progress.json"+"_md5_"+GetMD5(JSON_progress_data_file) + ".json")
            shutil.copyfile(JSON_progress_data_file,newFileName)
    with open(JSON_progress_data_file,'wb') as f:
        f.write(bytes(json.dumps(jsondata,indent=2,sort_keys=True),'utf-8'))

def timeStamped(fname, fmt='%Y-%m-%d-%H-%M-%S_{fname}'):
    return datetime.now().strftime(fmt).format(fname=fname)

GLOBAL_JSON_DATA = {}

def DownloadPackagesList(local_temp_file_name):
    try:
        print ("Downloading All Packages list from: %s" % (colored(MAIN_Packages_List_Link,'green')) )
        r = requests.get(MAIN_Packages_List_Link, timeout=600)
        content=r.content
        if os.path.exists(local_temp_file_name):
            os.remove(local_temp_file_name)
        with open(local_temp_file_name, 'wb') as f:
            data=r.content
            f.write(data)
        return True
    except Exception as ex:
        print (ex)
    return None

def LoadLocalPackageList(local_temp_file_name):
    global GLOBAL_JSON_DATA
    content=None
    with open(local_temp_file_name, 'r') as f:
        content=f.read()
    tree = html.fromstring(content)
    package_list = [package for package in tree.xpath('//a/text()')]
    # sort it
    package_list.sort()
   
    # check old progress json file, if it exists, load it, and them compare if we have new package
    if os.path.exists(JSON_progress_data_file):
        print (colored("Making a backup and Loading existing json progress file: %s" %JSON_progress_data_file,'green'))
        with open (JSON_progress_data_file,'rb') as f:
            GLOBAL_JSON_DATA = json.loads(f.read())
        # shutil.copyfile(JSON_progress_data_file,JSON_progress_data_file+"_md5_"+GetMD5(JSON_progress_data_file) + ".json")
    else:
        print (colored("No Previous progress file found, Creating new progress file: %s" %JSON_progress_data_file,'green'))
        for p in package_list:
            GLOBAL_JSON_DATA[p] = {"last_serial": None}
    
    # remove blacklisted from global_json_data
    if not os.path.exists(BlackListFile):
        print (colored("Blacklist file couldn't be found, creating one from template, review it and run the script again",'red'))
        shutil.copyfile(os.path.join(base_scirpt_path,"__blacklist_template"),BlackListFile)# Copy from template to destination
        exit (1)
    print (colored('Loading blacklist packages...','green'))
    BaclList_list = []
    with open(BlackListFile,'r') as f:
        line = f.readline()
        cnt = 1
        while line:
            # print("Line {}: {}".format(cnt, line.strip()))
            line = f.readline()
            if line:
                line=line.strip()
                if not str(line).startswith("#"):
                    BaclList_list.append(line)
                    cnt += 1
    print (colored("Filtering out blacklisted packages, if you recently blacklisted downloaded package, you will have to manually delete its data, I'm not doing this for you...",'red'))
    print (colored("I'm not doing this because you may want to initially download the package, then stop future re-runs of the same package, got it?",'red'))
    for p in package_list:
        if p not in BaclList_list:
            if p not in GLOBAL_JSON_DATA: # this will cover the case if an item was blacklisted in previous progress, and now we want it now , AND, it will cover the case for new packages added to pypi
                 GLOBAL_JSON_DATA[p] = {"last_serial": None}
    for p in BaclList_list: # this will cover the case if an item was wanted in previous progress, and now we need to ignore it
        if p in GLOBAL_JSON_DATA:
            del GLOBAL_JSON_DATA[p]
    print("Total Number of pacakges: %s" % (colored(len(package_list),'cyan')))
    print("Total Number of pacakges NOT including blacklisted: %s" % (colored(len(GLOBAL_JSON_DATA),'cyan')))

    # clear package_list since we are not using it anymore
    package_list = None
    WriteProgressJSON(GLOBAL_JSON_DATA,saveBackup=True)

def start(argv):
    # I want to get the path of app.py
    global GLOBAL_JSON_DATA
    
    
    if not os.path.exists(ROOT_FOLDER_NAME):
        os.makedirs(ROOT_FOLDER_NAME,exist_ok=True)
    if not os.path.exists(working_path):
        os.makedirs(working_path, exist_ok=True)
    if not os.path.exists(packages_data_path):
        os.makedirs(packages_data_path, exist_ok=True)

    if not os.path.exists(logfile_path):
        os.makedirs(logfile_path, exist_ok=True)
    
    #check if black list file does not exists
    
    
    local_temp_file_name = os.path.join(working_path, "htmlfiles.temp.html")
    if not os.path.exists(local_temp_file_name):
        if not DownloadPackagesList(local_temp_file_name):
            exit("Failed to download packages list")
    # open file for reading
    LoadLocalPackageList(local_temp_file_name)

    
    
    # return
    process_update()
    # # delete index.temp.json
    LastUpdateFile = os.path.join(working_path,timeStamped("_last_updated"))
    print (colored("Writing last update file: %s"%LastUpdateFile,'red'))
    with open(LastUpdateFile,"w") as f:
        f.write(timeStamped(""))

    print(colored("Download of all packages completed, Do you want to check for updated packages?",'cyan'))
    while True:
        answer = input(colored("Enter yes or no: ",'magenta'))
        if answer.lower() == "yes":
            pass
            break
        elif answer.lower() == "no":
            break
        else:
            print(colored("just yes or no, I'll not accept any other stupid answer",'red'))
    # os.remove(local_temp_file_name)
    return
    # installRequired.CheckRequiredModuels(required_modules)


def WriteTextFile(filename,data):
    with open (filename,'a+') as f:
        f.writelines(data)

def SaveAdnAppendToErrorLog(data):
    # timeS = datetime.now().strftime('FailedList__%H_%M_%d_%m_%Y.log.json')
    try:
        with open(logFileName, "a+") as outfile:
            outfile.write(data)
    except Exception as ex:
        print (ex)


# ProcessPools = []
DownloadPool = None
def signal_handler(sig, frame):
    global DownloadPool
    if DownloadPool:
        DownloadPool.terminate()
    print('\nYou pressed Ctrl+C!')
    print('\nTerminating All Processes')
    # for p in ProcessPools:
    #     p.termincate()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)

def normalize(name): # got it from: https://www.python.org/dev/peps/pep-0503/
    return re.sub(r"[-_.]+", "-", name).lower()

# outputQueue = Queue(MaxItemsToProcess)
def WriteFailedFile(filefail,txt,overwrite=False):
    if overwrite:
        with open(filefail, 'w') as f:
            f.write(str(txt))
    else: # append
        with open(filefail, 'a+') as f:
            f.write(str(txt))


def DownloadPackage(package_file):
    numberOfTries = 0
    Failed=True
    Error=None
    try:
        while numberOfTries<MaxNumberOfDownloadRetries:
            file_path = os.path.join(package_file['downloadPath'],package_file['filename'])
            Download=True
            sha256=None
            if os.path.exists(file_path): #if exists, check its sha256, maybe we don't need to redownload it
                sha256=GetSHA256(file_path)
                if sha256==package_file['digests']['sha256']:
                    Download=False
            if Download:
                with requests.get(package_file['url'], stream=True,timeout=10) as r:
                    with open(file_path, 'wb') as f:
                        shutil.copyfileobj(r.raw, f,length=DONWLOAD_CHUNK_SIZE_MB * 1024 * 1024)

                sha256=GetSHA256(file_path)
            if sha256==package_file['digests']['sha256']:
                # if it has signature, download it
                if package_file['has_sig'] == True:
                    r=requests.get(package_file['url'] + ".asc")
                    with open (file_path + ".asc",'wb') as f:
                        f.write(r.content)
                Failed=False
                break
            numberOfTries += 1
        # if download is successfull, append this to downloaded_releases
        # if not Failed:
        #     downloaded_releases.append(package_file)   
        
    except Exception as ex:
        Error = str.format("Error in Downlading: %s" %(ex))
        # ErrorLog = "File %s\n%s\n" % (key, ex)
        # SaveAdnAppendToErrorLog(ErrorLog)
        Failed = True

    return Failed,Error,package_file
def DownloadAndProcessesItemJob(key):
    global DownloadPool
    normalize_package_name = normalize(key)
    # steps to be done
    # 1- Get the json file, and save a copy in the respected folder
    # 2- Download all files into required folder
    # 3- Generate index.html file for the package
    # set last serial to the same value as in json file
    # save __lastserial as text file withn package folder
    # Get the json file
    try:
        r = requests.get(JSON_Info_Link_Prefix + normalize_package_name + "/json/",timeout=10)
        package_path = os.path.join(packages_data_path,normalize_package_name)
        package_json_path = os.path.join(package_path,"json")
        jsonfile = os.path.join(package_json_path,"index.json")
        indexfile = os.path.join(package_path,"index.html")
        serialfile = os.path.join(package_path,"__lastserial")
        errorfile = os.path.join(package_path,"__errors")
        genericErrorfile = os.path.join(package_path,"__generic_error")
        binariespath = os.path.join(package_path,"binaries")
        os.makedirs(binariespath,exist_ok=True)
        os.makedirs(package_json_path,exist_ok=True)
        # if there was an exists error file, delete it
        if os.path.exists(errorfile):
            os.remove(errorfile)
        # if there wasgeneric error file, delete it
        if os.path.exists(genericErrorfile):
            os.remove(genericErrorfile)
        #if below fails, no need to go any further, just return
        jsonObj=None
        try:
            jsonContent_raw = r.content
            jsonObj = json.loads(jsonContent_raw) # i'll re-write the json with indent, I cannot read this shit as single line, and its better to make sure we actually downloading a json file
        except Exception as ex:
            WriteFailedFile(errorfile,str.format("Error in getting json: %s" %(ex)),overwrite=True)
            return
        
        
        with open(jsonfile,'wb') as f:
            f.write(bytes(json.dumps(jsonObj,indent=2),'utf-8'))
        last_serial = jsonObj['last_serial']
        releases = jsonObj['releases']
        index_html_string = str(INDEX_HTML_TEMPLATE)
        
        downloaded_releases = []
        sorted_releases = sorted(releases, key=parse_version)
        packages_to_download = []
        for r in sorted_releases:
            for rr in releases[r]:
                package_file = {"filename":rr['filename'],"size":rr['size'],"url":rr['url'],"packagetype":rr['packagetype'],"requires_python":rr['requires_python'],"has_sig":rr['has_sig'],"digests":rr['digests'],"downloadPath":binariespath}
                packages_to_download.append(package_file)
        DownloadPool = Pool(processes=MaxDownloadProcess)
        # got the below from: https://stackoverflow.com/questions/41920124/multiprocessing-use-tqdm-to-display-a-progress-bar/45276885
        results = DownloadPool.imap(DownloadPackage,packages_to_download)
        # add them to processpools

        DownloadPool.close()
        DownloadPool.join()

        for r in results:
            failed,errorvalue,pfile=r
            if failed:
                WriteFailedFile(errorfile,str.format("Error in Downlading: %s" %(errorvalue)),overwrite=False)
            else:
                downloaded_releases.append(pfile)
            
        DownloadPool=None
        # write the index.html file
        links_html_string = ""
        for d in downloaded_releases:
            extras = ""
            href_copy = str(INDEX_HTML_LINKS_TEMPLATE)
            # <a href="@@@FILE_URL@@@">@@@FILE_NAME@@@</a><br/>
            sha256 = d['digests']['sha256']
            href_copy = href_copy.replace("@@@FILE_NAME@@@",d['filename'])
            href_copy = href_copy.replace("@@@FILE_URL@@@", "binaries/%s#sha256=%s" %(d['filename'],sha256) )
            if d['requires_python'] is not None:
                extras += " data-requires-python=\"" + htmlescape.escape(d['requires_python']) +"\" "
            if d['has_sig'] == True:
                extras += " data-gpg-sig=\"true\" "
            href_copy = href_copy.replace("@@@EXTRAS@@@",extras)
            links_html_string += href_copy + "\n"
        index_html_string=index_html_string.replace("@@@PACKAGE_NAME@@@",normalize_package_name)
        index_html_string=index_html_string.replace("@@@SERIAL@@@",str.format("%d"%last_serial))
        index_html_string=index_html_string.replace("@@@LINKS@@@",links_html_string)
        # write index.html
        if os.path.exists(indexfile):
            os.remove(indexfile)
        with open(indexfile,'wb') as f:
            f.write(bytes(index_html_string,'utf-8'))
        # write serial file
        if os.path.exists(serialfile):
            os.remove(serialfile)
        with open(serialfile,'w') as f:
            f.write(str.format("%d"%last_serial))
        # item['last_serial'] = last_serial
        
    except Exception as ex:
        WriteFailedFile(genericErrorfile,str.format("Other Errors: %s" %(ex)),overwrite=True) # here an error can occur because of ctrl+c press, thats why I'm saving this into new file
        # ErrorLog = "Pacakge %s\n%s\n" % (key, ex)
        # SaveAdnAppendToErrorLog(ErrorLog)
        
    return

def WriteMainIndexHTML():
    mainIndexFile = os.path.join(packages_data_path,"index.html")
    htmlData = str(MAIN_INDEX_HTML_TEMPLATE)
    links = ""
    extras = ""
    for p in GLOBAL_JSON_DATA:
        if GLOBAL_JSON_DATA[p]["last_serial"] is None or GLOBAL_JSON_DATA[p]["last_serial"]==0: # ignore not finished, or failed
            continue
        normalized = normalize(p)
        href_copy = str(INDEX_HTML_LINKS_TEMPLATE)
        href_copy = href_copy.replace("@@@FILE_NAME@@@",normalized)
        # href_copy = href_copy.replace("@@@FILE_URL@@@", "/simple/%s/" %(normalized) ) # I think using relative path better
        href_copy = href_copy.replace("@@@FILE_URL@@@", "%s/" %(normalized) )
        href_copy = href_copy.replace("@@@EXTRAS@@@",extras) # we will never have extras in main index.html
        links += href_copy + "\n"
    htmlData=htmlData.replace("@@@LINKS@@@",links)
    if os.path.exists(mainIndexFile):
        os.remove(mainIndexFile)
    with open(mainIndexFile,'w') as f:
        f.write(htmlData)


def process_update():
    global GLOBAL_JSON_DATA,ProcessPools
    print (colored("Checking Initial Download for packages, at this stage we are NOT updating downloaded packages",'cyan'))
    # in this stage, we will just check if we have the json file for ever package in the list
    # if we don't have the json file, we will append the package to the list of ToProcess
    
    TotalProcessed = 0
    Total = len(GLOBAL_JSON_DATA)
    To_Initial_Process_Sorted = []
    for k in GLOBAL_JSON_DATA:
        if GLOBAL_JSON_DATA[k]["last_serial"] is None:
            To_Initial_Process_Sorted.append(k)# GLOBAL_JSON_DATA[k]["InitialProcessed"] = False
        else:
            TotalProcessed += 1
    To_Initial_Process_Sorted.sort()
    # with open ("temp.sorted",'w') as f:
    #     for i in To_Initial_Process_Sorted:
    #         f.write(str(i) + "\n")
    # WriteProgressJSON(GLOBAL_JSON_DATA,saveBackup=True)
    print("Total Number of finished initial download pacakges: %s  out of  %s" % (colored(TotalProcessed,'cyan'),colored(Total,'red')))
    # starting_index = To_Initial_Process_Sorted.index("numpy") # a very easy and nice way to test out single package download
    starting_index = 0 
    Batch_Index = 0
    All_records=len(To_Initial_Process_Sorted)
    Total_Number_of_Batches = math.ceil(All_records/BatchSize)
    print (colored('Total Number of batches: %d with %d packages for each batch'%(Total_Number_of_Batches,BatchSize),'cyan'))
    BatchBackupCounter = 0
    while starting_index < All_records:
        Total_To_Process = BatchSize
        if All_records - starting_index < BatchSize:
            Total_To_Process = All_records - starting_index
            print (colored('Total to process less than Max Allowed, Changing total to: %d'% (Total_To_Process),'red'))
        print (colored("Processing Batch %d     of     %d"%(Batch_Index + 1,Total_Number_of_Batches)   ,'green'))
        itemBatch = To_Initial_Process_Sorted[starting_index:starting_index+Total_To_Process]
        printIndex = 0
        packagesProcessString= "["
        for i in itemBatch:
            packagesProcessString += str(printIndex) + "-" + normalize(i) + ", "
            printIndex += 1
        packagesProcessString = packagesProcessString[:-2]
        packagesProcessString += "]"
        print (colored(packagesProcessString,'blue'))
        

        # we are processing package by package, each package will get multiple processes for downloading
        list(tqdm.tqdm(map(DownloadAndProcessesItemJob,itemBatch), total=len(itemBatch), ))

     

        starting_index += Total_To_Process
        Batch_Index += 1
        # write back progress
        BatchBackupCounter += 1
        # check each package __lastserial file
        for p in itemBatch:
            normalize_package_name = normalize(p)
            package_path = os.path.join(packages_data_path,normalize_package_name)
            serialfile = os.path.join(package_path,"__lastserial")
            if os.path.exists(serialfile):
                with open(serialfile,'r') as f:
                    GLOBAL_JSON_DATA[p]['last_serial'] = int(f.read(),10)
            else:
                GLOBAL_JSON_DATA[p]['last_serial'] = 0

        if BatchBackupCounter >= BackupProgeressAfterBatches:
            print (colored("Backup Batches Counter= %d , Backing up Progress file, and create a backup" % BatchBackupCounter, 'magenta'))
            BatchBackupCounter = 0 # reset the counter
            WriteProgressJSON(GLOBAL_JSON_DATA,saveBackup=True)
        else:
            WriteProgressJSON(GLOBAL_JSON_DATA,saveBackup=False)
        print (colored("Writing new Main Index.html File...",'green'))
        WriteMainIndexHTML()
        
        # UpdateLastSeqFile(itemBatch[-1]['seq']) # last item sequence number in batch
    WriteProgressJSON(GLOBAL_JSON_DATA,saveBackup=True) # just make another backup once we finish
    print(colored('Done :)','cyan'))
    #TODO: we still have to write the logic for getting updates :(
