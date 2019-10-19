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
from datetime import datetime
# I'm using thead pool, because its easier and I can use global variables easily with it, We don't need high processing power for this project, just multi thread
from multiprocessing.pool import ThreadPool
from lxml import html# pip install lxml
from termcolor import colored
from zipfile import ZipFile
import tqdm  # pip3 install tqdm
import re

MaxItemsToProcess = 30
ROOT_FOLDER_NAME = "d:/PYPI/"
MAIN_Packages_List_Link = "https://pypi.org/simple/"
JSON_Info_Link_Prefix = "https://pypi.org/pypi/"

"""
I'll follow this folder structure

ROOT
    - data
        - package-name
            - binaries
            - json
                index.json
            __lastserial
"""

working_path = os.path.join(ROOT_FOLDER_NAME,"sync_data_indexes")
packages_data_path = os.path.join(ROOT_FOLDER_NAME, "simple")
logfile_path = os.path.join(working_path, "logs")
JSON_progress_data_file = os.path.join(working_path,"__progress.json")
BlackListFile = os.path.join(working_path,"__blacklist")
logFileName = os.path.join(logfile_path,datetime.now().strftime('FailedList_%d-%m-%Y_%H_%M.log'))


SkipDownloadingListFile=True

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
            shutil.copyfile(JSON_progress_data_file,JSON_progress_data_file+"_md5_"+GetMD5(JSON_progress_data_file) + ".json")
    with open(JSON_progress_data_file,'wb') as f:
        f.write(bytes(json.dumps(jsondata,sort_keys=True),'utf-8'))

GLOBAL_JSON_DATA = {}

def start(argv):
    # I want to get the path of app.py
    global GLOBAL_JSON_DATA
    base_scirpt_path = os.path.dirname(os.path.realpath(__file__))
    
    if not os.path.exists(ROOT_FOLDER_NAME):
        os.makedirs(ROOT_FOLDER_NAME,exist_ok=True)
    if not os.path.exists(working_path):
        os.makedirs(working_path, exist_ok=True)
    if not os.path.exists(packages_data_path):
        os.makedirs(packages_data_path, exist_ok=True)

    if not os.path.exists(logfile_path):
        os.makedirs(logfile_path, exist_ok=True)
    
    #check if black list file does not exists
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
    content=None
    local_temp_file_name = os.path.join(working_path, "htmlfiles.temp.html")
    if not SkipDownloadingListFile or not os.path.exists(local_temp_file_name):
        print ("Downloading All Packages list from: %s" % (colored(MAIN_Packages_List_Link,'green')) )
        r = requests.get(MAIN_Packages_List_Link, timeout=600)
        content=r.content
        if os.path.exists(local_temp_file_name):
            os.remove(local_temp_file_name)
        with open(local_temp_file_name, 'wb') as f:
            data=r.content
            f.write(data)
    else:
        print ("as requested, Skipping the download of all packages list, using existing data")
    # open file for reading
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
            GLOBAL_JSON_DATA[p] = {"lastserial": None}
    print (colored("Filtering out blacklisted packages, if you recently added already downloaded package, you will have to manually delete its data, I'm not doing this for you...",'red'))
    print (colored("I'm not doing this because you may want to initially download the package, then stop future re-runs of the same package, got it?",'red'))
    for p in package_list:
        if p not in BaclList_list:
            if p not in GLOBAL_JSON_DATA: # this will cover the case if an item was blacklisted in previous progress, and now we want it now , AND, it will cover the case for new packages added to pypi
                 GLOBAL_JSON_DATA[p] = {"lastserial": None}
    # remove blacklisted from global_json_data
    for p in BaclList_list: # this will cover the case if an item was wanted in previous progress, and now we need to ignore it
        if p in GLOBAL_JSON_DATA:
            del GLOBAL_JSON_DATA[p]

    WriteProgressJSON(GLOBAL_JSON_DATA,saveBackup=True)
    print("Total Number of pacakges: %s" % (colored(len(package_list),'cyan')))
    print("Total Number of pacakges NOT including blacklisted: %s" % (colored(len(GLOBAL_JSON_DATA),'cyan')))

    # clear package_list since we are not using it anymore
    package_list = None
    # return
    process_update()
    # # delete index.temp.json

    # os.remove(local_temp_file_name)
    return
    # installRequired.CheckRequiredModuels(required_modules)

CatalogJsonFilesToProcess = []

def WriteTextFile(filename,data):
    with open (filename,'w') as f:
        f.writelines(data)

def SaveAdnAppendToErrorLog(data):
    # timeS = datetime.now().strftime('FailedList__%H_%M_%d_%m_%Y.log.json')
    try:
        with open(logFileName, "a+") as outfile:
            outfile.write(data)
    except Exception as ex:
        print (ex)


def signal_handler(sig, frame):
    print('\nYou pressed Ctrl+C!')
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)



def DownloadAndProcessesItemJob(item):
    package_name= item['id']
    packageFolderRoot = os.path.join(packages_path,item['id'])
    packageFolderTar = os.path.join(packageFolderRoot,"-")
    rev_file = os.path.join(packageFolderRoot,"__rev")
    item_rev=item['changes'][0]['rev'].strip()
    package_name_url_safe = urllib.parse.quote(package_name, safe='')
    json_index_file = os.path.join(packageFolderRoot,"index.json")
    # first we need to download the json file and name it as index.json
    if 'deleted' in item:
        if item['deleted']==True:
            if os.path.exists(packageFolderRoot):
                shutil.rmtree(packageFolderRoot)
            return # skip this item
    try:
        os.makedirs(packageFolderTar,exist_ok=True) # this will make all folders required, including "-" which is used to store the tar balls
    except Exception as ex:
        ErrorLog = "Sequence %d\n%s\n%s\n%s\n%s" % (item['seq'],package_name,item_rev, packageFolderTar, ex)
        SaveAdnAppendToErrorLog(ErrorLog)
        return
    
    # we will store a file indicating latest revision we processed
    CurrentRev=None
    # ShouldProcess=False
    if os.path.exists(rev_file):
        with open (rev_file,'r') as f:
            CurrentRev=f.readline().strip()
    if CurrentRev:
        if CurrentRev==item_rev:
            # print(colored("package '%s' with same rev %s number, will be skipped"%(item['id'],item_rev),'red'))
            return
    try:
        #write json index file
        downloadURL = SkimDB_Main_Registry_Link + package_name_url_safe
        r = requests.get(downloadURL,timeout=20)
        json_raw=r.content
        with open(json_index_file, 'wb') as f:
            f.write(json_raw)
        jsonObj = json.loads(json_raw)
        # now we will download all tar balls
        AllGood = True
        versions_dict = jsonObj['versions']
        for k in versions_dict:
            try:
                tarBallDownloadLink = versions_dict[k]['dist']['tarball']
                r = requests.get(tarBallDownloadLink, timeout=600)
                fname = tarBallDownloadLink.rsplit('/', 1)[-1]
                tarBallLocalFile=os.path.join(packageFolderTar,fname)
                with open(tarBallLocalFile, 'wb') as f:
                    f.write(r.content)
            except Exception as ex:
                AllGood = False
                ErrorLog = "Sequence %d\n%s\n%s\n%s\n%s" % (item['seq'],package_name,item_rev, tarBallDownloadLink, ex)
                SaveAdnAppendToErrorLog(ErrorLog)
        if AllGood: # if all good, write the rev file, so we will never process this sequence again, unless its updated
            WriteTextFile(rev_file,item_rev)
    except Exception as ex:
        ErrorLog = "Sequence %d\n%s\n%s\n%s\n%s" % (item['seq'],package_name,item_rev, downloadURL, ex)
        SaveAdnAppendToErrorLog(ErrorLog)


def process_update():
    global GLOBAL_JSON_DATA
    print (colored("Checking Initial Download for packages, at this stage we are NOT updating downloaded packages"),'cyan')
    # in this stage, we will just check if we have the json file for ever package in the list
    # if we don't have the json file, we will append the package to the list of ToProcess
    
    TotalProcessed = 0
    Total = len(GLOBAL_JSON_DATA)
    To_Initial_Process_Sorted = []
    for k in GLOBAL_JSON_DATA:
        if GLOBAL_JSON_DATA[k]["lastserial"] is None:
            To_Initial_Process_Sorted.append(k)# GLOBAL_JSON_DATA[k]["InitialProcessed"] = False
        else:
            TotalProcessed += 1
    To_Initial_Process_Sorted.sort()

    # WriteProgressJSON(GLOBAL_JSON_DATA,saveBackup=True)
    print("Total Number of finished initial download pacakges: %s  out of  %s" % (colored(TotalProcessed,'cyan'),colored(Total,'red')))
    # print("Total Number of pacakges NOT including blacklisted: %s" % (colored(len(GLOBAL_JSON_DATA),'cyan')))
    starting_index = 0
    Batch_Index = 0
    All_records=len(To_Initial_Process_Sorted)
    Total_Number_of_Batches = math.ceil(All_records/MaxItemsToProcess)
    print (colored('Total Number of batches: %d with %d packages for each batch'%(Total_Number_of_Batches,MaxItemsToProcess),'cyan'))
    while starting_index < All_records:
        Total_To_Process = MaxItemsToProcess
        if All_records - starting_index < MaxItemsToProcess:
            Total_To_Process = All_records - starting_index
            print (colored('Total to process less than Max Allowed, Changing total to: %d'% (Total_To_Process),'red'))
        continue
        print (colored("Processing Batch %d     of     %d"%(Batch_Index,Total_Number_of_Batches)   ,'green'))
        itemBatch = To_Initial_Process_Sorted[starting_index:starting_index+Total_To_Process]
        pool = ThreadPool(processes=MaxItemsToProcess)
        # got the below from: https://stackoverflow.com/questions/41920124/multiprocessing-use-tqdm-to-display-a-progress-bar/45276885
        list(tqdm.tqdm(pool.imap(DownloadAndProcessesItemJob,itemBatch), total=len(itemBatch), ))

        pool.close()
        pool.join()
        starting_index += Total_To_Process
        Batch_Index += 1
        # UpdateLastSeqFile(itemBatch[-1]['seq']) # last item sequence number in batch
         
    print(colored('Done :)','cyan'))

