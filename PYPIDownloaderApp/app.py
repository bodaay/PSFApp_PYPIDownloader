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
from termcolor import colored
from zipfile import ZipFile
import tqdm  # pip3 install tqdm
import re

MaxItemsToProcess = 30
ROOT_FOLDER_NAME = "e:/NPM/"
SkimDB_Main_Registry_Link = "https://skimdb.npmjs.com/registry/"
working_path = os.path.join(ROOT_FOLDER_NAME,"sync_data_indexes")
packages_path = os.path.join(ROOT_FOLDER_NAME, "data")
logfile_path = os.path.join(working_path, "logs")
LastSeqFile = os.path.join(working_path,"__lastsequece")
logFileName = os.path.join(logfile_path,datetime.now().strftime('FailedList_%d-%m-%Y_%H_%M.log'))
   

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

def UpdateLastSeqFile(sequncenumer):
    with open(LastSeqFile,'w') as f:
        f.write(str(sequncenumer))

def start(argv):
    # I want to get the path of app.py
    #base_path = os.path.dirname(os.path.realpath(__file__))

    if not os.path.exists(working_path):
        os.makedirs(working_path, exist_ok=True)
    if not os.path.exists(packages_path):
        os.makedirs(packages_path, exist_ok=True)
    if not os.path.exists(logfile_path):
        os.makedirs(logfile_path, exist_ok=True)
    
    print ("Connecting to SkimDB to get latest Stats...")
    r = requests.get(SkimDB_Main_Registry_Link, timeout=600)
    statsJson = json.loads(r.content)
    # print(statsJson)
    print ("Total Number of packages: "+ colored(str(statsJson['doc_count']),'red'))
    LatestSeq = "0"
    if os.path.exists(LastSeqFile):
        with open(LastSeqFile,'r') as ls:
            LatestSeq=  ls.readline()
    if LatestSeq == str(statsJson['committed_update_seq']):
        print (colored('No Updates since latest run, nothing to do...Bye','red'))
    ChangesFeedURLSuffix="_changes?feed=normal&style=all_docs&since=" + LatestSeq
    local_temp_file_name = os.path.join(working_path, "changesfeed.temp.json")
    if os.path.exists(local_temp_file_name):
        os.remove(local_temp_file_name)
    r = requests.get(SkimDB_Main_Registry_Link + ChangesFeedURLSuffix)
    print ("Last Proccessed Squence: %s  out of %s  \n"%(colored(LatestSeq,'cyan'),colored(str(statsJson['committed_update_seq']),'red')))
    with open(local_temp_file_name, 'wb') as f:
        data=r.content
        f.write(data)
        print("Total Downloaded: "+ colored("%s"%humanbytes(len(data)),'cyan') +"     \r")
    # test only
    # UpdateLastSeqFile(str(statsJson['committed_update_seq'])) # delete me later, we should do this at very late stage


    
    process_update(local_temp_file_name)
    # # delete index.temp.json

    # os.remove(local_temp_file_name)
    return
    # installRequired.CheckRequiredModuels(required_modules)

# https://www.nuget.org/api/v2/package/vlc/1.1.8


# lock = Lock()

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
    
def process_update(json_file):
    global CatalogJsonFilesToProcess
    with open(json_file, 'r') as jsonfile:
        jsonObj = json.loads(jsonfile.read()) # this may take really long time, for the first run
        print(colored('Sorting out records, this may take some time...','red'))
        results = jsonObj['results']
        results_sorted = sorted(results, key=lambda k: k['seq']) 
        print(colored('finished sorting','cyan'))
        print (colored('Processing items in batches','green'))
        starting_index = 0
        Batch_Index = 0
        All_records=len(results_sorted)
        Total_Number_of_Batches = math.ceil(All_records/MaxItemsToProcess)
        print (colored('Total Number of batches: %d'%(Total_Number_of_Batches),'cyan'))
        while starting_index < All_records:
            Total_To_Process = MaxItemsToProcess
            if All_records - starting_index < MaxItemsToProcess:
                Total_To_Process = All_records - starting_index
                print (colored('Total to process less than Max Allowed, Changing total to: %d'% (Total_To_Process),'red'))
            print (colored("Processing Batch %d     of     %d"%(Batch_Index,Total_Number_of_Batches)   ,'green'))
            itemBatch = results_sorted[starting_index:starting_index+Total_To_Process]
            pool = ThreadPool(processes=MaxItemsToProcess)
            # got the below from: https://stackoverflow.com/questions/41920124/multiprocessing-use-tqdm-to-display-a-progress-bar/45276885
            list(tqdm.tqdm(pool.imap(DownloadAndProcessesItemJob,
                                    itemBatch), total=len(itemBatch), ))

            pool.close()
            pool.join()
            starting_index += Total_To_Process
            Batch_Index += 1
            UpdateLastSeqFile(itemBatch[-1]['seq']) # last item sequence number in batch
         
        print(colored('Done :)','cyan'))

