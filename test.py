import requests


header = requests.head("https://pypi.org/simple/tqdm/")
print (header.headers['X-PyPI-Last-Serial'])