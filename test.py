import requests


header = requests.head("https://pypi.org/simple/apppath/")
print (header.headers['X-PyPI-Last-Serial'])