import os
import pandas as pd
import sqlite3
import datetime
import calendar
import requests
import io
import time
import re
import holidays
import zipfile
import boto3
from botocore.handlers import disable_signing

cabi_start_date = datetime.datetime(2010,9,19,0,0)
date_format_standard = '%Y-%m-%d %H:%M:%S'
max_days_request_cabitracker = 7
sleep_time_cabitracker = 5 # seconds

raw_data_dir = r'C:\Users\rek\Desktop\GH\cabi-predict\data\0_raw'

# :::::::: data_dir, vc_key

def get_tables(db):
    table_names=[]
    conn = sqlite3.connect(db)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        table_names = [ttt[0] for ttt in tables]
        conn.close()
    except:
        conn.close()
    return(table_names)

def most_recent_timestamp(db,table,datecol):
    '''
    Return most recent timestamp (column: datecol) in table of database db
    This function assumes all timestamps in db are already strings written in date_format_standard
    If table does not exist, return cabi_start_date
    '''
    if (isinstance(datecol,list)):
        datecol=datecol[0] # if inconsistent datecol name, use the single col resulting from preproc
    table_names = get_tables(db)
    if (table not in table_names):
        return(cabi_start_date)
    conn=sqlite3.connect(db)
    try:
        query = "select "+datecol+" from "+table\
                    +" WHERE "+datecol+">'"+cabi_start_date.strftime('%Y-%m-%d')+"'"\
                    +" ORDER BY "+datecol+" DESC LIMIT 1"  # ++: CREATE INDEX?
        date_df = pd.read_sql_query(query, conn)
        most_recent = datetime.datetime.strptime(date_df.to_numpy()[0][0],'%Y-%m-%d %H:%M:%S')\
                        if len(date_df) else cabi_start_date
        most_recent = max(cabi_start_date,most_recent)
        conn.close()
        return(most_recent)
    except:
        conn.close()
        print("SQL Query did not work, returning cabi_start_date as most_recent")
        return(cabi_start_date)
        
        
    
def read_trip_history(db,tname,mrt,kw):
    """
    Retrieve new trip_history files from Capital Bikeshare's System Data S3 Bucket
    https://www.capitalbikeshare.com/system-data
    Determine whether to read each item in bucket by:
        parse filename to find string identifying YYYY or YYYYMM
        compare that date vs. most recent timestamp mrt.
        Read new months only.
    """
    
    # for each file available at S3:
        # is it a zip? If so, interpret Y/YM
        # filter: if zip and Y/M after mrt, download the zip
        # get csv filenames inside zip, containing no slashes
        # read_csv
    # return naive pd.concat(all newly read dataframes)
    os.makedirs(raw_data_dir,exist_ok=True)
    cabi_bucket_name = 'capitalbikeshare-data'
    s3resource = boto3.resource('s3')
    s3resource.meta.client.meta.events.register('choose-signer.s3.*', disable_signing)
    s3bucket = s3resource.Bucket(cabi_bucket_name)
    dfs = [pd.DataFrame()] # initz w/ empty DF 
    for obj in s3bucket.objects.all():
        if (os.path.splitext(obj.key) and (os.path.splitext(obj.key)[-1].lower()=='.zip')):
            zname = os.path.split(obj.key)[-1]
            YM_cand = [s for s in zname.split('-') if ((s.isdigit()) and (s[:2]=='20'))]
            assert(len(YM_cand)<2)
            if (YM_cand):
                Y=int(YM_cand[0][:4])
                M=int(YM_cand[0][4:] or '12')
                if (datetime.datetime(Y,M,15) > mrt): # hack: assumes each month comes at once
                    print('Reading file %s...' % obj.key)
                    targetzipfile=os.path.join(raw_data_dir,obj.key)
                    s3bucket.download_file(obj.key, targetzipfile)
                    zfile = zipfile.ZipFile(open(targetzipfile,'rb'))
                    csvs = [x for x in zfile.namelist() if (('/' not in x))] 
                    # stopped checking extension b/c July 2019 file omits it (=> 356645 missing rows)
                    for c in csvs:
                        dfs.append(pd.read_csv(io.BytesIO(zfile.read(c))))
                else:
                    print('Skipping file %s, which has presumably been read previously' % obj.key)
            else:
                print('Skipping file %s, cannot identify date string in filename' % obj.key)
        else:
            print('Skipping file %s because it is not a zip' % obj.key)
    return(pd.concat(dfs,axis=0))

def read_current_outages(db,tname,mrt,kw):
    # This table should always be written with if_exists='replace'
        # current_outages get converted to past_outages as soon as they're completed
    uri_cto_current = r'http://cabitracker.com/status.php?format=json'
    tic=time.time()
    print('Reading Current Outage data from CabiTracker...')
    cto_raw = requests.get(uri_cto_current)
    print('Execution Time(s): %.2f'%(time.time()-tic))
    timestamp = datetime.datetime.now().strftime(date_format_standard)
    df_cto0 = pd.read_json(io.BytesIO(cto_raw.content))
    return(pd.concat([pd.Series(timestamp,index=df_cto0.index,name='timestamp_now'),df_cto0],axis=1))

def read_past_outages(db,tname,mrt,kw):    
    """
    Retrieve dock outage data from cabitracker
    start_date, end_date = datetime.dates (inclusive) defining time period
    cabitracker retrieves outages based on the "End" time of each outage
    per_month => int, divide each month into # date-ranges, hack to prevent burnout requests
    refresh_all => bool. If True, read all data anew.
                        If False, reset start_date to date of most recent DB entry. 
            (if one is trying to recover any missing data before that, must use refresh_all=True with specific dates)
    """
    uri_cto_past_gen = r'http://cabitracker.com/downloadoutage.php?s=%s&e=%s'
           # two parameters for uri: s=startdate and e=enddate
           # request will fail if too much data, but we cannot probe its length before reading!
           # safety: just request a small amount at a time.
           # 7-day request period has worked fine through eo2020 data.
                # but could easily fail if outages modestly increase in future
                # 15-day request period failed for ~10% of spring months
                
    start_date = max(mrt.date(),datetime.date(2016,10,1)) # first date avail at cabitracker is 2016-10-01
    end_date = datetime.date.today()
    total_days = 1 + (end_date-start_date).days
    dfs = []
    for j in range(0,total_days,max_days_request_cabitracker):
        d0 = start_date + datetime.timedelta(days=j)
        d1 = start_date + datetime.timedelta(days=j+max_days_request_cabitracker-1)
        d1 = min(d1,end_date)
        (s0,s1) = (d0.strftime('%Y-%m-%d'),d1.strftime('%Y-%m-%d'))
        try:
            uri = uri_cto_past_gen % (s0,s1)
            print('Retrieving cabitracker outage data between %s and %s ...' % (s0,s1))
            outages_object = requests.get(uri)
            dfs.append(pd.read_csv(io.BytesIO(outages_object.content)))
        except:
            print('       Failed to process data between %s and %s !!!' % (s0,s1))
        time.sleep(5)
    return(pd.concat(dfs,axis=0))
        
    
def read_weather(db,tname,mrt,kw):
    vc_url_base = r'https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/weatherdata/history?'
    weather_dateformat_request = '%Y-%m-%dT%H:%M:%S'
    weather_dateformat_rawreturn = kw['raw_date_formats']['weather']['date_time']
    startdatetime = mrt + datetime.timedelta(minutes=30)
    enddatetime = kw['now']
    vc_file = r'C:\Users\rek\.credentials\vc.txt'
    with open(vc_file) as f:
        key_vc = f.read()
    d_vc = {'goal':'history',
            'startDateTime':startdatetime.strftime(weather_dateformat_request),
           'endDateTime':enddatetime.strftime(weather_dateformat_request),
           'aggregateHours':str(1),
           'contentType':'csv',
           'unitGroup':'us',
           'locations':'Washington,DC',
           'key':key_vc,
            'includeAstronomy':'true',
            'shortColumnNames':'true',
            'collectStationContribution':'true'
           }
    query_parameters = ('&'.join(('%s=%s' % (k,d_vc[k])) for k in d_vc))
    vc_url_full = vc_url_base + query_parameters
    print(startdatetime)
    print(enddatetime)
    print(vc_url_full[:170])
    assert False, "stopping here"
    tic=time.time()
    print('Reading new Weather Data from Visual Crossing...')
    ####################vcr_raw = requests.get(vc_url_full)    # check for cost b4 running. full set is $8.00
    print('Execution Time(s): %.2f'%(time.time()-tic))
    dfw_raw = pd.read_csv(io.BytesIO(vcr_raw.content))
    dfw_raw.to_json(path_or_buf='weather_backup_'+enddatetime.strftime(date_format_standard)+'.json')
    return(dfw_raw)


def read_holidays(db,tname,mrt,kw):
    # holidays is a very small table. Easy to just get this one anew every update.
    h_dc = (holidays.US(state='DC',years=range(mrt.year,5+kw['now'].year)))
    df_holidays = pd.DataFrame.from_dict(h_dc,orient='index',columns=['hol_name'])\
                .reset_index().rename(columns={'index':'date'})
    return(df_holidays)
    
    
    

    
    
def read_data_update(db,tables=None,startover=False,startover_freeonly=True,now=None):
    '''
    Update the cabi database with newest data
    Each table in input db is presumed to be accurate & complete up to its most recent entry.
    This function read_data_update will find any newer data and append it.
    Preserve Raw data format, except for::
        1) field names => .lower().replace(' ','_')
        2) all dates/datetimes stored in DB will be converted to a standardized string format
    
    db: file path to database where raw data is and/or will be stored
    tables: dict. Keys should match defaults below. Allows custom table names, if desired
    startover: ignore all existing data and read everything from scratch. Default False (update only)
    startover_freeonly: even if starting over, refrain from re-accessing data behind paywalls.
            Default True (so that weather data can be preserved even if starting over everything else)
    No return value
    '''
    default_tables = {k:k for k in \
                      ['trip_history','past_outages','current_outages','weather','holidays']}
    default_tables.update(tables or {})
    tables=default_tables
    kw={}
    kw['datetimekeys4sort']={'trip_history':['mixed_start_datetime','start_date','started_at'],\
                                 'past_outages':'end','current_outages':'start',\
                                 'weather':'datetime','holidays':'date'}
    kw['raw_date_formats']={'trip_history':{f:date_format_standard for f in\
                    ['mixed_start_datetime','start_date','end_date','started_at','ended_at']},\
            'past_outages':{'start':date_format_standard,'end':date_format_standard},
            'current_outages':{'timestamp_now':date_format_standard,'start':date_format_standard},\
            'weather':{'datetime':'%m/%d/%Y %H:%M:%S'},
            'holidays':{'date':None}}
    if_exists = {'holidays':'append','current_outages':'replace'}  # default is 'append' if unspecified
    #paid_tables = ['weather']
    #raw_date_formats = {'weather':'%m/%d/%Y %H:%M:%S'}  # default: date_format_standard
    if (now is None):
        kw['now']=datetime.datetime.now()
    else:
        assert isinstance(now,datetime.datetime), "'now' argument must be an instance of type datetime.datetime"
        kw['now']=now
    globs = globals()
    
    for (t,table_name) in tables.items():
        datecol = kw['datetimekeys4sort'][t]
        datefields_rawformats = kw['raw_date_formats'][t]
        mrt = most_recent_timestamp(db,table_name,datecol)
        fun_name = 'read_'+t
        df_new = globs[fun_name](db,table_name,mrt,kw) # get new data
        if (len(df_new)==0):
            continue
        # 1) Standardize field names
        col_renames = {c:c.lower().replace(" ","_") for c in df_new.columns}
        df_new = df_new.rename(columns=col_renames) # standardize fieldname format
        # 2) Collect datetimekeys4sort in one column, if necessary
        if (isinstance(datecol,list)):
            # date format is not consistent for this source
            # copy into datecol[0] so that a single column holds all dates for sorting
            (target_col,candidate_cols)=(datecol[0],[c for c in datecol[1:] if c in df_new.columns])
            datecol=datecol[0]
            if (target_col not in df_new.columns):
                df_new = pd.concat([pd.Series(\
                            cabi_start_date.strftime(kw['raw_date_formats'][t][datecol]),\
                                              name=datecol,index=df_new.index),df_new],axis=1)
            for c in candidate_cols:
                df_new[target_col].update(df_new[c])
        # 3) Standardize all date formats
        for dfield in datefields_rawformats: # standardize all date formats
            if dfield in df_new.columns:
                tic=time.time()
                print('Converting date format for %s, field %s ...' % (t,dfield))
                if isinstance(df_new[dfield].iloc[0],datetime.date):
                    # only holidays include date objects, all other sources provide strings
                    df_new[dfield] = df_new[dfield].astype(str)
                    # hack... but holidays will remain short strings from datetime.date() not datetime.datetime()
                else:
                    # all data sources other than holidays:
                    df_new[dfield] = pd.to_datetime(df_new[dfield],format=datefields_rawformats[dfield])\
                                            .dt.strftime(date_format_standard)
                print(time.time()-tic)
        # 4) Sort and/or dedupe rows:        
        tic=time.time()
        print('Sorting / deduping rows, %s ... ' % t)
        df_new = df_new.sort_values(datecol)\
                        .reset_index(drop=True)
        dfndc = df_new[datecol]
        startrow=0
        mrt_str = mrt.strftime(date_format_standard)
        while ((startrow<len(df_new)) and \
                       (dfndc.iloc[startrow] <= mrt_str)):
            # ++: compare hashes here to allow insertion if sources evolve historical data?
            startrow+=1
        print(time.time()-tic)
        # 5) Write to DB:
        tic=time.time()
        print('Writing table %s to database %s ...' % (table_name,db))
        if (if_exists.get(t,'append')=='replace'): # always write entire table if 'replace'
            startrow=0
        if (startrow<len(df_new)):
            conn=sqlite3.connect(db)
            try:
                df_new.iloc[startrow:].to_sql(table_name,conn,if_exists=if_exists.get(t,'append'),index=False)
                conn.close()
            except:
                conn.close()
                print('    Write failed. Instead writing to a backup json file')
                df_new.iloc[startrow:].to_json(path_or_buf=t+'_backup_'+\
                           datetime.datetime.now().strftime(date_format_standard)+'.json')
        print(time.time()-tic)