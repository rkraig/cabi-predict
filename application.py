from flask import Flask,render_template,request,redirect
import folium
import dill
import pandas as pd
import datetime
import glob
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
    
for oldMap in glob.glob('./static/bikeMap-2*.html'):
    os.remove(oldMap)
    
    
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
df = pd.DataFrame(testcase).reindex_axis(app.vars['predictorCols'],axis=1)
demandPredictions = app.vars['model'].predict(df)
app.vars['stations']['bikeDemand'] = demandPredictions[0][0::2]
app.vars['stations']['dockDemand'] = demandPredictions[0][1::2]
#print(app.vars['stations'])

#app.vars['gjS'] = df_to_geojson(app.vars['stations'],['terminalname','name','bikeDemand','dockDemand'],
#                                    lat='lat', lon='long')


#print(df)
#print(predictions.shape)

#app.vars['demand'] = app.vars['model'].predict
#print(app.vars['gjS']['features'][:2])
#print(app.vars['stations'].head()) 
#print(type(app.vars['stations']['terminalname'].iloc[0]))
app.questions={}

app.nquestions=len(app.questions)
#should be 3

def pOutage(muX,muY,nowX):
    return sum([poisson.pmf(x,muX)*poisson.cdf(x-nowX,muY) 
                for x in range(nowX,1+poisson.ppf(0.9995,muX).astype(int))])


@app.route('/index',methods=['GET','POST'])
def index():
    nquestions=app.nquestions
    if request.method == 'GET':
        if (app.vars['firstTime']):
            return render_template('intro_beforeMap.html')#,num=nquestions)
        else:
            try:
                #print(app.vars['predictions'])
                #print(type(app.vars['predictions']))
                #print(app.vars['predictions'].shape)
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
                #mergedDF['pEmpty'] = 
                sendGJ = df_to_geojson(mergedDF,['terminalname','name',
                                                 'nbbikes','nbemptydocks','bikeDemand','dockDemand',
                                                 'ppf0005_B','ppf0005_D',
                                                 'pEmpty','pFull'],
                                              lat='lat', lon='long')
                return render_template('withMap.html',num=app.vars['window'],
                                   #mapFileName=app.vars['bikeMap_Path'],
                                   gjFC_StationData=sendGJ)
            except:    
                print('fail')
                return render_template('withoutMap.html',num=app.vars['window'],
                                   #mapFileName=app.vars['bikeMap_Path'],
                                   gjFC_StationData=app.vars['gjS'])
    else:
        #request was a POST
        tempInput = request.form['myWindow']
        app.vars['firstTime']=False
        try:
            app.vars['window'] = min([int(tempInput),60]) # limit one hour
        except:
            app.vars['window'] = 15 # default to 15 minutes, if bad input
        #myBikes=folium.Map(location=[38.894,-77.04],zoom_start=14,
        #            tiles='Stamen Terrain',width=960,height=720)
        #print(datetime.datetime.now())
        #for sDex in range(len(app.vars['stations'])):
        #    row = app.vars['stations'].iloc[sDex]
        #    ss = row['terminalname']
            #ss = app.vars['stations']['terminalname'].iloc[sDex]
            #row = app.vars['stations'].loc[ss]
        #    lat = row['lat']
        #    lon = row['long']
            #name = row['name']
            #bikeDemand = app.vars['predictions'][0,2*sDex]
            #dockDemand = app.vars['predictions'][0,2*sDex+1]
            #folium.CircleMarker([lat,lon],radius=50,
            #        popup=str(ss)+': d_bph:'+str(bikeDemand)+', d_dph:'+str(dockDemand),
            #        color='#ff86cc',fill_color='#3186cc',
            #        ).add_to(myBikes)
        #print(datetime.datetime.now())
        #dt_suffix = ''.join([x for x in str(datetime.datetime.now()) if x in '0123456789'])
        #app.vars['bikeMap_Path'] = './static/bikeMap-'+dt_suffix+'.html'
        #myBikes.save(app.vars['bikeMap_Path'])
        #print('just saved map')
        return redirect('/index')


'''
@app.route('/main_lulu')
def main_lulu2():
    if 678==0 : return render_template('end_lulu.html')
    return redirect('/next_lulu')

#####################################
## IMPORTANT: I have separated /next_lulu INTO GET AND POST
## You can also do this in one function, with If and Else.

@app.route('/next_lulu',methods=['GET'])
def next_lulu():  #remember the function name does not need to match the URL
    # for clarity (temp variables):
    n=app.nquestions-len(app.questions)+1
    q=app.questions.keys()[0] #python indexes at 0
    # q = list(app.questions.keys())[0] #python indexes at 0
	# Anuar Edition for Pytho 3.4 from following Stackflow source: http://stackoverflow.com/questions/28467967/unhashable-type-dict-keys-works-in-ver-2-7-5-but-not-in-3-4
	# In python3, as opposed to python2, keys returns an iterable set-like view object, not a list. Thus, the need to call the list function on that object to convert it into a list.
    a1=app.questions[q][0]
    a2=app.questions[q][1]
    a3=app.questions[q][2]

    # save current question
    app.currentq=q

    return render_template('layout_lulu.html',num=n,question=q,ans1=a1,ans2=a2,ans3=a3)

@app.route('/next_lulu',methods=['POST'])
def next_lulu2():  #can't have two functions with the same name
    # Here, we will collect data from the user.
    # Then, we return to the main function, so it can tell us whether to 
    # display another question page, or to show the end page.

    f=open('%s_%s.txt'%(app.vars['name'],app.vars['age']),'a') #a is for append
    f.write('%s\n'%(app.currentq))
    f.write('%s\n\n'%(request.form['answer_from_layout_lulu'])) #do you know where answer_lulu comes from?
    f.close()

    app.questions.pop(app.currentq)

    return redirect('/main_lulu')
'''

if __name__ == "__main__":
    app.run()
