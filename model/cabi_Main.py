# -*- coding: utf-8 -*-

import cabi_Func as cf
import os
import pickle
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn import cross_validation
from sklearn import metrics
from sklearn import grid_search


dbName = 'cabi_201604.db'
tableTH = 'TH'
tableW  = 'Weather'
tableS  = 'Stations'
tableD = 'docksMerged'
tableB = 'bikesMerged'
weatherFile = 'KDCA___csv_mesowest_2010-2015.csv'
stationsCSV = 'stationInfo_v8.csv'

# ASSEMBLE RAW DATA:
if (not((os.path.isfile(dbName)))): # assume that TH is done, if db exists
    cf.TH_csv2db(134,154,dbName,tableTH)
    cf.weather_csv2db(weatherFile,dbName,tableW)
    cf.stations_csv2db(stationsCSV,dbName,tableS)
DF0 = cf.rek_readSQL(dbName,tableTH)
tossStations = cf.badStationLocs()
DF1 = DF0.loc[~((DF0['startLoc'].isin(tossStations)) | (DF0['endLoc'].isin(tossStations)))]
W = cf.rek_readSQL(dbName,tableW)
S = cf.rek_readSQL(dbName,tableS)
S.drop('index', axis=1, inplace=True)
S.index = S.terminalname
dDF = cf.mergeData(DF1,W,S)
dock_Columns = [x for x in dDF if x.startswith('D_')]
bike_Columns = [x for x in dDF if x.startswith('B_')]
bDF = dDF.copy()
bDF = bDF.drop(dock_Columns,axis=1)
dDF = dDF.drop(bike_Columns,axis=1)
cf.rek_writeSQL(dbName,tableD,dDF,'w')
cf.rek_writeSQL(dbName,tableB,bDF,'w')

pickle.dump(bDF, open( "save_bikes0912_000.p", "wb" ) )
pickle.dump(dDF, open( "save_docks0912_000.p", "wb" ) )








dbName = 'cabi_000'
tableTH = 'TH'
tableW  = 'Weather'
tableS  = 'Stations'
tableD = 'docksMerged'
tableB = 'bikesMerged'
weatherFile = 'KDCA___csv_mesowest_2010-2015.csv'
stationsCSV = 'stationInfo_v8.csv'


fB = open('save_bikes0912_000.p','rb')
fD = open('save_docks0912_000.p','rb')
bDF = pickle.load(fB)
dDF = pickle.load(fD)
S = cf.rek_readSQL(dbName,tableS)
S.drop('index', axis=1, inplace=True)
S.index = S.terminalname
stationStrings = map(str,S.terminalname)

predictorColumnNames = [cc for cc in dDF.columns if ('D_' not in cc)]
responseColumnsNamesB = [cc for cc in bDF.columns if ('B_' in cc)]
responseColumnsNamesD = [cc for cc in dDF.columns if ('D_' in cc)]
RCN = responseColumnsNamesB+responseColumnsNamesD

fullDF = pd.concat([dDF[predictorColumnNames],
                                bDF[responseColumnsNamesB],
                                dDF[responseColumnsNamesD]],axis=1)
allDemand = pd.DataFrame()
for ss in stationStrings:
    for bd_ in ['B_','D_']:
        allDemand[bd_+ss] = fullDF[[x for x in RCN if ((bd_ in x) and (ss in x))]].sum(axis=1)
systemWideDemand = pd.DataFrame()
for bd_ in ['B_','D_']:
    systemWideDemand[bd_] = allDemand[[x for x in allDemand.columns if x.startswith(bd_)]].sum(axis=1)
predictors = dDF[predictorColumnNames].drop(['timeW','precip06h','dewpointF'],1)

'''
maxFeats = range(2,5)
MSL = range(3,8)
estRF_preCV = RandomForestRegressor(n_estimators=500,n_jobs=4)
gs = grid_search.GridSearchCV(
    estRF_preCV,
    {"max_features": range(2,5), "min_samples_leaf": range(3,8)},
    cv=10,  # 5-fold cross validation
    n_jobs=4,  # run each hyperparameter in one of two parallel jobs
    scoring='mean_squared_error'
)
%time my_GS_Fit = gs.fit(predictors.iloc[:2000],systemWideDemand.iloc[:2000])
print gs.best_params_
'''



estRF = RandomForestRegressor(max_features=3,min_samples_leaf=5,n_estimators=500,n_jobs=4)
myFit = estRF.fit(predictors, allDemand)
pp = myFit.predict(predictors)












stationStrings = map(str,S.terminalname)
CM = ['C','M']
B_List = ['B_'+cm+'_'+ss for cm in CM for ss in stationStrings]
D_List = ['D_'+cm+'_'+ss for cm in CM for ss in stationStrings]
colsS = {}
colsS['B']={}
colsS['D']={}
for s in S.terminalname:
    colsS['B'][s] = ['B_'+cm+'_'+str(s) for cm in CM]
    colsS['D'][s] = ['D_'+cm+'_'+str(s) for cm in CM]



# Weekdays only:
bs45 = (bDF[((bDF.year==2014)|(bDF.year==2015)) & (bDF.DOW<=5) & (bDF.isHol==0)])
bsG = bs45.groupby(['hour'])
BSSA = bsG[B_List].mean()
ds45 = (dDF[((dDF.year==2014)|(dDF.year==2015)) & (dDF.DOW<=5) & (dDF.isHol==0)])
dsG = ds45.groupby(['hour'])
DSSA = dsG[D_List].mean()



for s in S.terminalname:
    BSSA[s] = BSSA[colsS['B'][s]].sum(axis=1)
    DSSA[s] = DSSA[colsS['D'][s]].sum(axis=1)
B_sumonly = BSSA[[x for x in BSSA.columns if type(x)==np.int64]].transpose()
D_sumonly = DSSA[[x for x in DSSA.columns if type(x)==np.int64]].transpose()



lats = [S.lat[S.terminalname==int(ss)] for ss in stationStrings]
lons = [S.long[S.terminalname==int(ss)] for ss in stationStrings]

flow = pd.DataFrame()
for h in range(24):
    flow['B_'+str(h)] = B_sumonly[h]
    flow['D_'+str(h)] = D_sumonly[h]
for h in range(24):
    flow['h_'+str(h)] = B_sumonly[h] - D_sumonly[h]
    

B={}
D={}
for h in range(24):
    B[h] = [BSSA.loc[h,['B_'+cm+'_'+ss for cm in CM]].sum() for ss in stationStrings]
    D[h] = [DSSA.loc[h,['D_'+cm+'_'+ss for cm in CM]].sum() for ss in stationStrings]

dfB_workdays = pd.DataFrame(B)
dfB_workdays.columns = ['B_'+str(x) for x in qwe.columns]
dfD_workdays = pd.DataFrame(D)
dfD_workdays.columns = ['D_'+str(x) for x in qwe.columns]
inflow_workdays = pd.DataFrame({h:(dfD_workdays['D_'+str(h)] - dfB_workdays['B_'+str(h)]) for h in B.keys()})

SH = pd.concat([S,flow],axis=1)
SH.to_csv('stationFlows.csv')


hourlyFlows_5D = pd.DataFrame(