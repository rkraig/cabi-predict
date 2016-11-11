from flask import Flask,render_template,request,redirect
#import folium
import dill
import pandas as pd
import datetime
import holidays
#import glob
import os
import json
import requests
from bs4 import BeautifulSoup
import re
import numpy as np
from scipy.stats import poisson

sec_2_msec = 1000 

def df_to_geojson(df, properties, lat='latitude', lon='longitude'):
        # Geoff Boeing
    geojson = {'type':'FeatureCollection', 'features':[]}
    for _, row in df.iterrows():
        feature = {'type':'Feature',
                   'properties':{},
                   'geometry':{'type':'Point',
                               'coordinates':[]}}
        feature['geometry']['coordinates'] = [row[lon],row[lat]]
        for prop in properties:
            feature['properties'][prop] = row[prop]
        geojson['features'].append(feature)
    return geojson

def getNumberFromOneTag_td(inTag):
    tempOutString = re.findall('(?<=\<td\>).*(?=.*\</td\>)',str(inTag))[0]
    tempOutString = ''.join([x for x in tempOutString if x in '0123456789.-'])
    #tempOutString = ''.join([x for x in tempOutString if x not in '%'])
    if (not(tempOutString)):
        return 0.0
    else:
        return float(tempOutString)

def getWeatherDataNow():
    # return current tempF, RH, windSpeed, precip01h, snowDepth
    wPage = 'http://w1.weather.gov/data/obhistory/KDCA.html'
    wBase = requests.get(wPage)
    wSoup = BeautifulSoup(wBase.content,"lxml")
    tt = wSoup.findAll('table')
    lenTT = [len(x) for x in tt]
    bigTable = tt[lenTT.index(max(lenTT))]
    allTR = bigTable.findAll('tr')
    numTDs = [len(x.findAll('td')) for x in allTR]
    firstDataRowDex = [(dex,x) for (dex,x) in enumerate(numTDs) if x>10][0][0]
    wData18 = allTR[firstDataRowDex].findAll('td')
    wNow={}
    wNow['tempF'] = getNumberFromOneTag_td(wData18[6])
    wNow['RH'] = getNumberFromOneTag_td(wData18[10])
    wNow['windSpeed'] = getNumberFromOneTag_td(wData18[2])
    wNow['precip01h'] = getNumberFromOneTag_td(wData18[15])
    wNow['snowDepth'] = 0.0 # hardwire this for now
    return wNow
    
def cabiFields():
    return ['id', 'installdate', 'installed', 'lastcommwithserver', 'lat',\
       'latestupdatetime', 'locked', 'long', 'name', 'nbbikes',\
       'nbemptydocks', 'public', 'removaldate', 'temporary',\
       'terminalname']
   
def idFields():
    return ['id','terminalname']
    
def timestampFields():
    return ['lastcommwithserver','latestupdatetime']
    
def dynamicFields():
    return ['nbbikes','nbemptydocks']
    
def staticFields():
    return [F for F in cabiFields() if not F in (idFields()+dynamicFields()+timestampFields())]    
    
def getDtype(fieldname):
    if fieldname in timestampFields():
        return np.int64
    elif fieldname in idFields():
        return np.uint16
    elif fieldname in dynamicFields():
        return np.uint8
    else:
        return str       
        
def getRealTimeDockStatusData(thisURL):
    # reads XML file, converts to pandas dataFrame. Each row is one station.
    #print('00a')
    cabiBase = requests.get(thisURL)
    cabiSoup = BeautifulSoup(cabiBase.content,"lxml")
    #print('00b')
    CC = cabiSoup.findChildren()
    fnSoup = [x.name for x in CC]
    sta = cabiSoup.findAll('station')
    allContents = [x.contents for x in sta]
    fieldsHere = [[re.search('(?<=\<)\w+(?=>)',str(entry)).group(0) \
                for entry in x] for x in allContents]
    valuesHere = [[re.sub('&amp;','&',re.search('(?<=>)[^\<]*(?=\<)',str(entry)).group(0)) \
                             for entry in x] for x in allContents]              
    dNew = {}
    for ff in range(len(fieldsHere[0])):    # assumes they're all identical!
        thisField = fieldsHere[0][ff]
        thisType = getDtype(thisField)
        try:
            dNew.update({thisField:[thisType(x[ff]) for x in valuesHere]})
        except:
            temptemp = [x[ff] for x in valuesHere]
            temp2 = [thisType(x) if (len(x)) else -999 for x in temptemp]
            dNew.update({thisField:temp2})  
    #overall_LastUpdate_sec = [int(CC[fnSoup.index('stations')].attrs['lastupdate'])/sec_2_msec]*(len(sta))
    #zipIt = zip([1000000*OLU for OLU in overall_LastUpdate_sec],dNew['id'])
    DF = pd.DataFrame(dNew)#,index=[sum(zz) for zz in zipIt])
    return DF[['terminalname','nbbikes','nbemptydocks']]
    
    
app = Flask(__name__)
app.vars={}
app.vars['firstTime']=True
app.vars['url2scrapeRT'] = 'https://www.capitalbikeshare.com/data/stations/bikeStations.xml'

app.vars['stations'] = dill.load(open('./model/S_000.p','rb'))

app.vars['model'] = dill.load(open('./model/rafo_30.p','rb'))
app.vars['predictorCols'] = ['DOW','DOY','hour','isHol','year',
                             'tempF','RH','windSpeed','precip01h','snowDepth']
testcase = {'DOW':[4],'DOY':[290],'hour':[18],'isHol':[0],'year':[2015],
                      'tempF':[68.0],'RH':[30.0],'windSpeed':[2.2],'precip01h':[0.0],'snowDepth':[0.0]}

nowPredictors = getWeatherDataNow()
holsThru2030 = holidays.US(years=range(2016,2030)).items()
todayIsAHoliday = datetime.date.today() in holidays.US(years=range(2016,2030))
nowDT = datetime.datetime.now()
nowPredictors['DOW'] = nowDT.isoweekday()
nowPredictors['DOY'] = nowDT.timetuple().tm_yday
nowPredictors['hour'] = nowDT.hour
nowPredictors['isHol'] = 1 if ((todayIsAHoliday) and (nowPredictors['DOW'] <= 5)) else 0
nowPredictors['year'] = nowDT.year
useCase = {k:[nowPredictors[k]] for k in nowPredictors}

#print(testcase)
#print(useCase)

df = pd.DataFrame(useCase).reindex_axis(app.vars['predictorCols'],axis=1)
demandPredictions = app.vars['model'].predict(df)
app.vars['stations']['bikeDemand'] = demandPredictions[0][0::2]
app.vars['stations']['dockDemand'] = demandPredictions[0][1::2]


def pOutage(muX,muY,nowX):
    return sum([poisson.pmf(x,muX)*poisson.cdf(x-nowX,muY) 
                for x in range(nowX,1+poisson.ppf(0.9995,muX).astype(int))])


@app.route('/',methods=['GET','POST'])
def index():
    if request.method == 'GET':
        if (app.vars['firstTime']):
            return render_template('intro_beforeMap.html')
        else:
            try:
                rtDF = getRealTimeDockStatusData(app.vars['url2scrapeRT'])
                mergedDF = (app.vars['stations']).merge(rtDF,'inner','terminalname')
                mergedDF['muBikesW'] = mergedDF['bikeDemand'] * app.vars['window']/60.
                mergedDF['muDocksW'] = mergedDF['dockDemand'] * app.vars['window']/60.
                mergedDF['ppf0005_B'] = 1+poisson.ppf(0.9995,mergedDF['muBikesW']).astype(int)
                mergedDF['ppf0005_D'] = 1+poisson.ppf(0.9995,mergedDF['muDocksW']).astype(int)
                mergedDF['pEmpty'] = mergedDF.apply(
                           lambda x: pOutage(x['muBikesW'],x['muDocksW'],x['nbbikes']), axis=1)
                mergedDF['pFull'] = mergedDF.apply(
                           lambda x: pOutage(x['muDocksW'],x['muBikesW'],x['nbemptydocks']), axis=1)
                sendGJ = df_to_geojson(mergedDF,['terminalname','name',
                                                 'nbbikes','nbemptydocks','bikeDemand','dockDemand',
                                                 'ppf0005_B','ppf0005_D',
                                                 'pEmpty','pFull'],
                                              lat='lat', lon='long')
                return render_template('withMap.html',num=app.vars['window'],
                                   gjFC_StationData=sendGJ)
            except:    
                #print('fail')
                return render_template('withoutMap.html',num=app.vars['window'],
                                   gjFC_StationData=app.vars['gjS'])
    else:
        #request was a POST
        tempInput = request.form['myWindow']
        app.vars['firstTime']=False
        try:
            app.vars['window'] = min([abs(int(float(tempInput))),60]) # limit one hour
        except:
            app.vars['window'] = 15 # default to 15 minutes, if input cannot be converted to numeric
        return redirect('/')


if __name__ == "__main__":
    myPort = int(os.environ.get('PORT',33507))
    app.run(host='0.0.0.0',port=myPort)
