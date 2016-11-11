# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
#import os
import re
import datetime
import time
import sqlite3
#from bs4 import BeautifulSoup

def unix2str(inTime):
    return datetime.datetime.fromtimestamp(int(inTime)).strftime('%Y-%m-%d %H:%M:%S')
    
def str2unix(inTime):  
    # assumes format like '1970-01-01 00:00:00'
    return time.mktime(datetime.datetime.strptime(inTime,'%Y-%m-%d %H:%M:%S').timetuple())    
    
def rek_readSQL(dbName,tableName):
    myConnection = sqlite3.connect(dbName)
    try:
        tableDF = pd.read_sql("SELECT * FROM "+tableName,myConnection)
    except:
        tableDF = []
    myConnection.close()
    return tableDF
    
def badStationLocs():
    return [00000,40000,40099,40098]    # throw out these non-existent stations
    
def rek_writeSQL(dbName,tableName,DF,wa):
    myConnection = sqlite3.connect(dbName)
    try:
        if (wa=='w'):
            DF.to_sql(tableName,myConnection,if_exists='replace')    
        elif (wa=='a'):
            DF.to_sql(tableName,myConnection,if_exists='append')
    except:
        print('error with rek_writeSQL')
    myConnection.close()

def get_cabiFieldMatcher():
    f = open('cabi_fieldMatcher.txt')
    lines = [LLINE.strip() for LLINE in f.readlines()]
    f.close()
    cfm_F = {}
    cfm_B = {}
    for ii in lines:
        [officialName,possibleNames] = ii.split(':')
        pNam = possibleNames.split(',')
        cfm_F.update({officialName:pNam})
        for nn in pNam:
            cfm_B.update({nn:officialName})
    return [cfm_F,cfm_B]
       
def csv2dic(csvfile,vInt=0):
    f = open(csvfile)
    lines = [LLINE.strip() for LLINE in f.readlines()]
    f.close()
    term_name = [re.findall('[^,]+',x) for x in lines]
    dd={}
    if vInt:
        for TN in term_name:
            dd.update({TN[1]:int(TN[0])})
    else:
        for TN in term_name:
            dd.update({TN[1]:TN[0]})
    return dd
    
def atoz():
    return 'abcdefghijklmnopqrstuvwxyz'    
    
def ismember(A,B):
    return [True if a in B else False for a in A]        
    
def listSelect(L,filterTF):
    return [el for (el, TF) in zip(L, filterTF) if TF]    
    
def dupeValues(A):
    return list(set([a for a in A if A.count(a) >= 2]))    

def fN_TH():
    return ['duration','startTime','endTime','startLoc','endLoc','member']
    
def fN_weatherW():
    return ['timestamp_KDCA','temp_F','RH','SKNT mph',\
                    'P01I in','P06I in','SNOW in','dewpointF']

def fN_weatherR():
    return ['timeW','tempF','RH','windSpeed',\
                    'precip01h','precip06h','snowDepth','dewpointF']


def reformatCabiField(idata,FN):
    if (FN=='duration'):
        try:
            odata = idata / 1000.0      # some files use numeric milliseconds
        except:
            # otherwise strings of 
            tuplist_HMS_str=[re.findall('(\d+)\D+(\d+)\D+(\d+)',x)[0] for x in idata]
            tuplist_HMS_int=[[int(x) for x in tup] for tup in tuplist_HMS_str]
            odata = [(3600*h + 60*m + s) for (h,m,s) in tuplist_HMS_int]
    elif (FN in ['startLoc','endLoc']):
        name2terminal = csv2dic('LUT___stationTerminalNames_revised.txt',1)
        idata = [(str(x)).strip() for x in idata]
        odata = [name2terminal[x] for x in idata]
    elif (FN in ['startTime','endTime']):
        if ('-' in idata.iloc[0]):
            tStr = '%Y-%m-%d %H:%M'
            #odata = [time.mktime(datetime.datetime.strptime(x,tStr).timetuple()) for x in idata]
            #tups_YMDhm_str = [re.findall('(\d+)-(\d+)-(\d+) (\d+):(\d+)',x)[0] for x in idata]
            #tups_YMDhm_int = [[int(x) for x in tup] for tup in tups_YMDhm_str]
            #odata = [(3600*h+60*mi+time.mktime(datetime.date(y,mo,d).timetuple())) \
            #                            for (y,mo,d,h,mi) in tups_YMDhm_int]
        else:
            tStr = '%m/%d/%Y %H:%M'
            #tups_MDYhm_str = [re.findall('(\d+)/(\d+)/(\d+) (\d+):(\d+)',x)[0] for x in idata]
            #tups_MDYhm_int = [[int(x) for x in tup] for tup in tups_MDYhm_str]
            #odata = [(3600*h+60*mi+time.mktime(datetime.date(y,mo,d).timetuple())) \
            #                            for (mo,d,y,h,mi) in tups_MDYhm_int]        
        odata = [time.mktime(datetime.datetime.strptime(x,tStr).timetuple()) for x in idata]
    elif (FN in ['member']):
        odata = ['C' if (r=='Casual') else 'M' for r in idata]
    return odata    

def TH_csv2db(yqStart,yqEnd,dbName,tableName):
    #origDIR = os.getcwd()
    #os.chdir(cabiDIR)
    y = yqStart / 10
    q = yqStart % 10
    yE = yqEnd / 10
    qE = yqEnd % 10
    [cfm_F,cfm_B] = get_cabiFieldMatcher()
    numRides=0
    while ((10*y+q) <= (10*yE+qE)):
        csvFilename = '20'+str(y)+'-Q'+str(q)+'-cabi-trip-history-data.csv'
        print('reading file: %s' % csvFilename)
        th = pd.read_csv(csvFilename)
        th.index = np.arange(numRides,numRides+len(th))
        cols=th.columns
        for col0 in cols:
            col = ''.join(listSelect(col0.lower(),ismember(col0.lower(),atoz())))
            if (col in cfm_B):
                FN = cfm_B[col]
                if FN in fN_TH():
                    print('    Processing field: %s' % FN)
                    th = th.rename(columns = {col0:FN})
                    th[FN] = reformatCabiField(th[FN],FN)
        th = th[fN_TH()]
        th.loc[:,'startHour'] = np.floor(th['startTime']/3600.0)
        th.loc[:,'endHour'] = np.floor(th['endTime']/3600.0)
        rek_writeSQL(dbName,tableName,th,'a')
        if (q < 4):
            q+=1
        else:
            y+=1
            q=1
        numRides += len(th)
    #os.chdir(origDIR)
    
def rmNansFromWeatherCol_withinTimeOffset(pSeries,timeW,offset):    
    filledDexes = np.flipud(np.where(~np.isnan(pSeries))[0])
    qSeries = pSeries.copy()
    for fd in filledDexes:
        time_fd = timeW[fd]
        time_prev = time_fd - offset
        minDex = min(np.where((timeW > time_prev))[0])
        qSeries[minDex:(fd+1)] = pSeries[fd]
    return qSeries
    
def replaceNansWithZeros(pSeries):
    nanDexes = np.where(np.isnan(pSeries))[0]
    qSeries = pSeries.copy()
    qSeries[nanDexes]=0
    return qSeries    
    
def dicTimeOffsetsWeatherFields():
    return {'precip01h':3600,'precip06h':21600,'snowDepth':21600}
    
def weather_csv2db(weatherFile,dbName,tableW):
    dfW0 = pd.read_csv(weatherFile)
    dfW1 = dfW0[fN_weatherW()]
    dfW1 = dfW1.rename(columns = {(fN_weatherW()[j]):(fN_weatherR()[j]) \
                        for j in range(len(fN_weatherW()))})    
    for col in dfW1.columns:
        print('Weather: reading column: %s' % col)
        print(time.clock())
        if (col=='timeW'):
            dfW1.timeW = dfW1.timeW.apply(lambda x: (re.findall('.*(?= E)',x)[0]))
            dfW1.timeW = dfW1.timeW.apply(lambda x: \
                    time.mktime(datetime.datetime.strptime(x,'%m-%d-%Y %H:%M').timetuple()))
        elif (col in ['precip01h','precip06h','snowDepth']):
            tOffset = dicTimeOffsetsWeatherFields()[col]
            dfW1[col] = rmNansFromWeatherCol_withinTimeOffset(dfW1[col],dfW1.timeW,tOffset)
            dfW1[col] = replaceNansWithZeros(dfW1[col])
        else:
            # just fill over the remaining missing data with nearby values. Not many of them:
            dfW1[col] = rmNansFromWeatherCol_withinTimeOffset(dfW1[col],dfW1.timeW,216000)
            dfW1[col] = replaceNansWithZeros(dfW1[col])
    rek_writeSQL(dbName,tableW,dfW1,'w')
    
def getDTypes_StationFields():
    return {'terminalname':int,'name':str,'lat':float,'long':float,'el':float}    

"""    
def stations_xml2db(stationsXML,dbName,tableS):
    fXML = open(stationsXML)
    xmlBody = fXML.readlines()[-1]
    cabiSoup = BeautifulSoup(xmlBody,"lxml")
    CC = cabiSoup.findChildren()
    #fnSoup = [x.name for x in CC]
    sta = cabiSoup.findAll('station')
    allContents = [x.contents for x in sta]
    fieldsHere = [[re.search('(?<=\<)\w+(?=>)',str(entry)).group(0) \
                for entry in x] for x in allContents]
    valuesHere = [[re.sub('&amp;','&',re.search('(?<=>)[^\<]*(?=\<)',str(entry)).group(0)) \
                             for entry in x] for x in allContents]              
    dNew = {}
    for ff in range(len(fieldsHere[0])):    # assumes they're all identical!
        thisField = fieldsHere[0][ff]
        if thisField in getDTypes_StationFields():
            thisType = getDTypes_StationFields()[thisField]
            dNew.update({thisField:[thisType(x[ff]) for x in valuesHere]})
    #dfS = pd.DataFrame(dNew,index=dNew['terminalname'])
    #return dfS
"""

def stations_csv2db(stationsCSV,dbName,tableS):
    dfS = pd.read_csv(stationsCSV)
    rek_writeSQL(dbName,tableS,dfS,'w')
    
def getMatchedRowDexes_origWeather(ts_Index,W):
    print('computing merged weather timestamps...')
    dexHI = [len(W.timeW[W.timeW<t]) for t in ts_Index]    
    looksign = [(2*ts_Index[ii] - sum(W.timeW.loc[(dexHI[ii]-1):dexHI[ii]])) \
                    for ii in range(len(ts_Index))]
    return [dexHI[ii] if (looksign[ii]>=0) else (dexHI[ii]-1) for ii in range(len(ts_Index))]                        
        
    
def getMergedWeatherDF(W,tStart,tEnd):
    # output pandas DF of all weather fields, indexed by on-hour timestamps
        # pick weather data closest to xx:30
    print('merging weather data...')
    h0 = int(np.floor(tStart/3600.0))
    hE = int(np.ceil(tEnd/3600.0))
    wIndex = range(h0,1+hE)                     # h in hours since unix0
    ts_Index = [1800+3600*x for x in wIndex]    # xx:30 in seconds
    w0Dexes = getMatchedRowDexes_origWeather(ts_Index,W)
    wMerged =  W.loc[w0Dexes]
    wMerged.index = wIndex
    wMerged = wMerged.drop('index',axis=1)
    return wMerged

def holidayList():
    holDF = pd.read_csv('holidays2010on.csv')
    temp1 = [(x.split('/')) for x in holDF.date]
    temp2 = [(int(x[2]),int(x[0]),int(x[1])) for x in temp1]
    return [datetime.date(*x) for x in temp2]    

def daysPerMonth():
    return [31,28,31,30,31,30,31,31,30,31,30,31]

def getTimeDF(tStart,tEnd):    
    holidays = holidayList()
    DPM = daysPerMonth()
    h0 = int(np.floor(tStart/3600.0))
    hE = int(np.ceil(tEnd/3600.0))
    wIndex = range(h0,1+hE)
    ts_Index = [3600*x for x in wIndex]    # xx:30 in seconds
    dtDate = [datetime.date.fromtimestamp(x) for x in ts_Index]
    dtDateTime = [datetime.datetime.fromtimestamp(x) for x in ts_Index]
    dTime = {}
    dTime['hour'] = [y.hour for y in dtDateTime]
    dTime['year'] = [x.year for x in dtDate]
    dTime['DOW'] = [x.isoweekday() for x in dtDate]
    dTime['DOY'] = [(x.day + sum(DPM[:(x.month-1)])) for x in dtDate]
    dTime['isHol'] = [1 if (x in holidays) else 0 for x in dtDate]
    dfTime = pd.DataFrame(dTime)
    dfTime.index = wIndex
    return dfTime
    
def strBikesDocks():
    return {'B':'start','D':'end'}    

def mergeData(DF1,W,S):
    # wish to output numerous SQL tables
        # B_C_31000, D_M_31096, etc.
    W_h = getMergedWeatherDF(W,min(DF1.startTime),max(DF1.endTime))
    time_h = getTimeDF(min(DF1.startTime),max(DF1.endTime))
    strBD = strBikesDocks()
    responses = ['B','D']
    members = ['C','M']
    uSta = S.terminalname.unique()
    dd = {}
    for r in responses:
        fThLoc  = strBD[r]+'Loc'
        fThHour = strBD[r]+'Hour'
        for s in uSta:
            print('r = %s, s = %s' % (r,s))
            matchesS = (DF1[DF1[fThLoc]==s])
            for m in members:
                matchesMS = (matchesS[matchesS['member']==m])
                tableName = ('%s_%s_%s' % (r,m,s))
                dd[tableName] = pd.Series(W_h.index,index=W_h.index)
                dd[tableName] = dd[tableName].apply(lambda x: np.count_nonzero(matchesMS[fThHour]==x))
    PDF = pd.DataFrame(dd)
    return (pd.concat([time_h,W_h,PDF],axis=1))