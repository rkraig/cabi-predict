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

cabi_start_datetime = datetime.datetime(2010,9,20,10,30)
datetime_format_standard = '%Y-%m-%d %H:%M:%S'
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

def extremal_timestamp(db,table,datecol,takewhich,kw):
    '''
    db: full path to database file
    table: name of table
    datecol: name of column to search for first or last date
    takewhich={'last','first'}
        # last: get most recent timestamp
        # first: get earliest timestamp
    Return most recent timestamp (column: datecol) in table of database db
    This function assumes that any timestamps existing in db 
            are strings that are written in datetime_format_standard
    If table does not exist, return startdate (first) or enddate (last)
    '''
    assert ((takewhich=='first') or (takewhich=='last')), "takewhich must be 'first' or 'last'"
    defaultvalue = (kw['enddate'] if (takewhich=='first') else kw['startdate'])
    if (isinstance(datecol,list)):
        datecol=datecol[0] # if inconsistent datecol name, use the single col resulting from preproc
    table_names = get_tables(db)
    if (table not in table_names):
        return(defaultvalue)
    conn=sqlite3.connect(db)
    try:
        fun_maxmin = 'min' if (takewhich=='first') else 'max'
        query = "select "+fun_maxmin+"("+datecol+") from "+table
        #query = "select "+datecol+" from "+table\
        #            +" WHERE "+datecol+">'"+cabi_start_datetime.strftime('%Y-%m-%d')+"'"\
        #            +" ORDER BY "+datecol\
        #            +(" LIMIT 1" if (takewhich=='first') else (" DESC LIMIT 1"))  # ++: CREATE INDEX?
        date_df = pd.read_sql_query(query, conn)
        result = datetime.datetime.strptime(date_df.to_numpy()[0][0],'%Y-%m-%d %H:%M:%S')\
                        if len(date_df) else cabi_start_datetime
        #result = max(cabi_start_datetime,result)
        conn.close()
        return(result)
    except:
        conn.close()
        print(("SQL Query did not work for table %s, column %s. "+\
                  "Returning default value for extremal_timestamp") % (table,datecol))
        return(defaultvalue)
        
        
    
def read_trip_history(db,tname,kw):
    """
    Retrieve new trip_history files from Capital Bikeshare's System Data S3 Bucket
    https://www.capitalbikeshare.com/system-data
    Determine whether to read each item in bucket by:
        parse filename to find string identifying YYYY or YYYYMM
        compare that date vs. most recent timestamp mrt.
        Read new months only.
    """
    
    # for each file available at S3:
        # if it's a zip:
        # interpret Y/YM
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
                M=int(YM_cand[0][4:] or '0') # M=0 if file covers entire year
                earliest_possible_inclusion=datetime.datetime(Y,(M or 1),1)
                M_temp=(M or 12)
                latest_possible_inclusion=datetime.datetime(Y,M_temp,1)+\
                            datetime.timedelta(days=calendar.monthrange(Y,M_temp)[1])
                print((Y,M,earliest_possible_inclusion,latest_possible_inclusion))
                if ((earliest_possible_inclusion<kw['endtime']) and \
                                    (latest_possible_inclusion>kw['starttime'])):
                    if ((kw['startover']) or \
                                (earliest_possible_inclusion<kw['fet']) or \
                                (latest_possible_inclusion>kw['let'])):
                        print('Reading file %s...' % obj.key)
                        targetzipfile=os.path.join(raw_data_dir,obj.key)
                        s3bucket.download_file(obj.key, targetzipfile)
                        zfile = zipfile.ZipFile(open(targetzipfile,'rb'))
                        csvs = [x for x in zfile.namelist() if (('/' not in x))] 
                        # stopped checking extension b/c July 2019 file omits ext !
                        for c in csvs:
                            dfs.append(pd.read_csv(io.BytesIO(zfile.read(c))))
                            print(dfs[-1].shape)
                    else:
                        print('Skipping file %s: it is entirely inside time bounds pre-existing in DB' % obj.key)
                else:
                    print('Skipping file %s: it is outside time bounds selected for reading' % obj.key)
            else:
                print('Skipping file %s: cannot identify date string in zipfilename' % obj.key)
        else:
            print('Skipping file %s: it is not a zip' % obj.key)
    return(pd.concat(dfs,axis=0))

def read_current_outages(db,tname,kw):
    # This table should always be written with if_exists='replace'
        # current_outages get converted to past_outages as soon as they're completed
    uri_cto_current = r'http://cabitracker.com/status.php?format=json'
    tic=time.time()
    print('Reading Current Outage data from CabiTracker...')
    cto_raw = requests.get(uri_cto_current)
    print('Execution Time(s): %.2f'%(time.time()-tic))
    timestamp = datetime.datetime.now().strftime(datetime_format_standard)
    df_cto0 = pd.read_json(io.BytesIO(cto_raw.content))
    return(pd.concat([pd.Series(timestamp,index=df_cto0.index,name='timestamp_now'),df_cto0],axis=1))

def read_past_outages(db,tname,kw):    
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
           # cabitracker request will fail if too much data
                # but there is no way to probe its length before attempting to read it
           # simple hack: just request a small amount at a time.
           # 7-day request period has worked fine through eo2020 data.
                # this could fail if outages increase 2x in future
                # 15-day request period failed for ~10% of spring months
                
    cabitracker_first_date = datetime.date(2016,10,1) # first date avail at cabitracker DB is 2016-10-01
    start_date = (max([kw['starttime'],cabitracker_first_date])).date()
    end_date = (min([kw['endtime'],datetime.datetime.now()])).date()
    
    if ((kw['startover']) and \
            (kw['reacquire_keyed_data'] or not(kw['requires_api_key'].get(tname,False)))):
        datebounds_for_request = [(start_date,end_date)]
    else:
        datebounds_for_request = [(start_date,kw['fet'].date()),\
                                  (kw['let'].date(),end_date)]
                                    # [interval before existing, interval after existing]
    dfs = []
    for interval in datebounds_for_request:
        (iv_start_date,iv_end_date) = interval
        total_days = 1 + (iv_end_date-iv_start_date).days
        for j in range(0,total_days,max_days_request_cabitracker):
            d0 = iv_start_date + datetime.timedelta(days=j)
            d1 = iv_start_date + datetime.timedelta(days=j+max_days_request_cabitracker-1)
            d1 = min(d1,iv_end_date)
            (s0,s1) = (d0.strftime('%Y-%m-%d'),d1.strftime('%Y-%m-%d'))
            try:
                uri = uri_cto_past_gen % (s0,s1)
                print('Retrieving cabitracker outage data between %s and %s ...' % (s0,s1))
                outages_object = requests.get(uri)
                dfs.append(pd.read_csv(io.BytesIO(outages_object.content)))
            except:
                # could try shorter time sub-intervals here in case of read failure
                print('       Failed to process data between %s and %s !!!' % (s0,s1))
            time.sleep(5)
    return(pd.concat(dfs,axis=0))
        
    
def read_weather(db,tname,kw):
    vc_url_base = r'https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/weatherdata/history?'
    weather_datetimeformat_request = '%Y-%m-%dT%H:%M:%S'
    weather_datetimeformat_rawreturn = kw['raw_datetime_formats']['weather']['datetime']
    five_mins = datetime.timedelta(minutes=5)  # hack: don't reacq endpts. We know that sampling_rate=1h
    format_dt_4svfile = ''.join([ch for ch in datetime_format_standard if (ch.isalpha() or ch=='%')])
    
    start_datetime = (max([kw['starttime'],cabi_start_date]))
    end_datetime = (min([kw['endtime'],datetime.datetime.now()]))
    
    if ((kw['startover']) and \
            (kw['reacquire_keyed_data'] or not(kw['requires_api_key'].get(tname,False)))):
        datetimebounds_for_request = [(start_datetime,end_datetime)]
    else:
        datetimebounds_for_request = [(start_datetime,kw['fet']-five_mins),\
                                  (kw['let']+five_mins,end_datetime)]
                                    # [interval before existing, interval after existing]
    dfs = []
    
    for interval in datetimebounds_for_request:
        (startdatetime,enddatetime) = interval
        d_vc = {'goal':'history',
                'startDateTime':startdatetime.strftime(weather_datetimeformat_request),
               'endDateTime':enddatetime.strftime(weather_datetimeformat_request),
               'aggregateHours':str(1),
               'contentType':'csv',
               'unitGroup':'us',
               'locations':'Washington,DC',
               'key':kw['key_'+tname],
                'includeAstronomy':'true',
                'shortColumnNames':'true',
                'collectStationContribution':'true'
               }
        query_parameters = ('&'.join(('%s=%s' % (k,d_vc[k])) for k in d_vc))
        vc_url_full = vc_url_base + query_parameters
        print(startdatetime)
        print(enddatetime)
        print(vc_url_full[:170]) # verify url structure, 170 cuts off and doesn't print key
        tic=time.time()
        print('Reading new Weather Data from Visual Crossing...')
        vcr_raw = requests.get(vc_url_full)    # check for cost b4 running. full set would be $9.00
        print('Execution Time(s): %.2f'%(time.time()-tic))
        dfw_raw = pd.read_csv(io.BytesIO(vcr_raw.content))
        dfw_raw.to_json(path_or_buf='weather_backup_ed='\
                        +enddatetime.strftime(format_dt_4svfile)+'_cur='\
                        +datetime.datetime.now().strftime(format_dt_4svfile)+'.json')
        dfs.append(dfw_raw)
        time.sleep(5)
    return(pd.concat(dfs,axis=0))


def read_holidays(db,tname,kw):
    # holidays is a very small table. Super easy to just reacquire it in full on every update.
    h_dc = (holidays.US(state='DC',\
                years=range(cabi_start_datetime.year,5+datetime.datetime.now().year)))
    df_holidays = pd.DataFrame.from_dict(h_dc,orient='index',columns=['hol_name'])\
                .reset_index().rename(columns={'index':'date'})
    return(df_holidays)

    
def old_read_data_update(db,tables=None,startover=False,startover_freeonly=True,now=None):
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
    kw['raw_date_formats']={'trip_history':{f:datetime_format_standard for f in\
                    ['mixed_start_datetime','start_date','end_date','started_at','ended_at']},\
            'past_outages':{'start':datetime_format_standard,'end':datetime_format_standard},
            'current_outages':{'timestamp_now':datetime_format_standard,'start':datetime_format_standard},\
            'weather':{'datetime':'%m/%d/%Y %H:%M:%S'},
            'holidays':{'date':None}}
    if_exists = {'holidays':'append','current_outages':'replace'}  # default is 'append' if unspecified
    #paid_tables = ['weather']
    #raw_date_formats = {'weather':'%m/%d/%Y %H:%M:%S'}  # default: datetime_format_standard
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
                            cabi_start_datetime.strftime(kw['raw_date_formats'][t][datecol]),\
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
                                            .dt.strftime(datetime_format_standard)
                print(time.time()-tic)
        # 4) Sort and/or dedupe rows:        
        tic=time.time()
        print('Sorting / deduping rows, %s ... ' % t)
        df_new = df_new.sort_values(datecol)\
                        .reset_index(drop=True)
        dfndc = df_new[datecol]
        startrow=0
        mrt_str = mrt.strftime(datetime_format_standard)
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
                           datetime.datetime.now().strftime(datetime_format_standard)+'.json')
        print(time.time()-tic)
        
def update_raw_data(datadir=None,db=None,tables=None,
                   starttime=None,endtime=None,
                   startover=False,reacquire_keyed_data=False,**kwargs):
    '''
    Inputs (all parameters are optional):
    datadir: folder location to read or write files to/from
        Default: use os.getcwd()
    db: name of SQL database for step 0 output. May or may not include a path
        Default name will be 'cabi0.db'
    tables: subset of tables to process.
        Default: None => process all tables for which a reader exists in this module
    starttime:
        Input: either a datetime.datetime object or a string in format YYYY-MM-DD
        Default value: 2010-09-20 11:00:00
        if startover=True, any pre-existing data from before starttime will be removed
    endtime:
        Input: either a datetime.datetime object or a string in format YYYY-MM-DD
        Default value: current time
        if startover=False, pre-existing data after endtime are not removed
    startover: if True, reacquire all data from scratch
                    NOTE: This option will remove any existing data from DB outside the time window specified
                if False, 
                    for each table: compute earliest_timestamp and most_recent_timestamp of existing table
                    if starttime < earliest, prepend any new data found between starttime and earliest
                    if endtime > most_recent, append any new data found between most_recent and endtime
                    NOTE: This option will preserve all existing data regardless of its timestamp
    reacquire_keyed_data:
        if startover==True:
            if reacquire_keyed_data==True:
                all data will be re-fetched, including data requiring an API key
                This option could result in multiple charges.
            if reacquired_keyed_data==False:
                data that require an api key are not re-fetched
        if startover==False:
            reacquired_keyed_data is irrelevant if (startover==False)
    kwargs: additionally, arbitrary parameter names can be passed into reader functions:
        API keys should be passed as "key_"+name_of_table.
        Example:
                key_weather = "here_goes_either_your_api_key_or_the_name_of_a_textfile_containing_the_key"
            assumption: file names will always contain "."
    '''
    if (datadir is None):
        datadir = os.getcwd()
    if (db is None):
        (dbdir,dbname) = (datadir,'cabi0.db')
        db = os.path.join(dbdir,dbname)
    (dbdir,dbname) = os.path.split(db)
    if (not(dbdir)):
        db = os.path.join(datadir,dbname)
    table_readers = {k:v for (k,v) in globals().items() \
                             if ((k.startswith('read_'))and(hasattr(v,'__call__')))}
    default_tables = [k[5:] for k in table_readers] # all strings for which a reader function exists
    if (tables is None):
        tables = default_tables
    else:
        tables = [t for t in tables if t in default_tables]
        
    if (isinstance(starttime,str)):
        try:
            starttime = datetime.datetime.strptime(starttime,datetime_format_standard)
        except:
            try:
                print('eurig')
                starttime = datetime.datetime.strptime(starttime,datetime_format_standard[:8]) # date w/ zero time
            except:
                starttime=cabi_start_datetime
    if (not(isinstance(starttime,datetime.datetime))):
        starttime=cabi_start_datetime
    starttime=max(starttime,cabi_start_datetime)
        
    if (isinstance(endtime,str)):
        try:
            endtime = datetime.datetime.strptime(endtime,datetime_format_standard)
        except:
            try:
                print('etui')
                endtime = datetime.datetime.strptime(endtime,datetime_format_standard[:8]) # date w/o time
            except:
                endtime=datetime.datetime.now()
    if (not(isinstance(endtime,datetime.datetime))):
        endtime=datetime.datetime.now()
    endtime=min(endtime,datetime.datetime.now())    
        
    keys_for_keyed_tables = [k for k in kwargs if k.startswith('key_')]
    for k in keys_for_keyed_tables:
        if ('.' in kwargs[k]):
            try:
                with open(kwargs[k]) as f:
                    apikey = f.read()
                kwargs[k]=apikey    
            except:
                pass
    vars_pushed_to_kwargs = ['datadir','db','tables',\
                      'startover','starttime','endtime','reacquire_keyed_data']
    locs=locals()
    kwargs.update({k:locs[k] for k in vars_pushed_to_kwargs})
    kwargs['datetimekeys4sort']={'trip_history':['mixed_start_datetime','start_date','started_at'],\
                                 'past_outages':'end','current_outages':'start',\
                                 'weather':'datetime','holidays':'date'}
    kwargs['raw_datetime_formats']={'trip_history':{f:datetime_format_standard for f in\
                    ['mixed_start_datetime','start_date','end_date','started_at','ended_at']},\
            'past_outages':{'start':datetime_format_standard,'end':datetime_format_standard},
            'current_outages':{'timestamp_now':datetime_format_standard,'start':datetime_format_standard},\
            'weather':{'datetime':'%m/%d/%Y %H:%M:%S'},
            'holidays':{'date':None}}
    kwargs['requires_api_key'] = {'weather':True}
    if_exists = {'holidays':'append','current_outages':'replace'}  # default is 'append' if unspecified
    globs=globals()
    print()
    print([k for k in globals()])
    print()
    print([k for k in locals()])
    print()
    print(kwargs)
    tic=time.time()
    for t in tables:
        print()
        dtcol = kwargs['datetimekeys4sort'][t]
        dtfields_rawformats = kwargs['raw_datetime_formats'][t]
        fet = extremal_timestamp(db,t,dtcol,'first',kwargs) # first existing timestamp in table t
        let = extremal_timestamp(db,t,dtcol,'last',kwargs)  # latest existing timestamp in table t
        kwargs.update({'fet':fet,'let':let})
        fun_name = 'read_'+t
        print((fet,let))
        df_new = globs[fun_name](db,t,kwargs) # get new data
        #print(dtcol)
        #print(dtfields_rawformats)
        print(df_new.shape)
        print((fun_name,fun_name in globs))
        print(time.time()-tic)
    return(kwargs)