import flask
from flask import request, jsonify
import sqlite3
import pandas as pd
import requests
import numpy as np
from difflib import SequenceMatcher
from fuzzywuzzy import fuzz

from flask_cors import CORS, cross_origin


app = flask.Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

app.config["DEBUG"] = True

@app.route("/")
@cross_origin()
def helloWorld():
  return "Hello, cross-origin-world!"


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def temp_to_hard(temp):
    if temp >= 13:
        return 10
    else:
        uk_steps = np.arange(-50, 20, 7)
        return np.argmax(uk_steps>temp)

def fuzz_search(namecol,name):
    if pd.isnull(namecol) == False:
        return fuzz.partial_ratio(namecol,name)
    else:
        return 0

def rainfall_to_moisture(rain):
    '''takes rainfall in mm/day'''
    if rain < 7:
        soil = 'D'
    elif rain < 14:
        soil = 'DM'
    elif rain < 21:
        soil = 'M'
    elif rain < 28:
        soil = 'MWe'
    else:
        soil = 'We'
    return soil    

def soil_value(js):
    temp = {}
    temp['name'] = js['name']
    temp['value'] = js['depths'][0]['values']['mean'] / js['unit_measure']['d_factor']
    return temp    

def content_to_heavy(content):
    '''takes list/array of [sand_content, silt_content, clay_content] in g per kg soil'''
    
    #make sure data is numpy array
    if type(content) != np.ndarray:
        content = np.array(content)
    
    #determine soil type from max content and std
    if (np.argmax(content) == 0) and (content.std() > 50):
        return 'L'
    elif (np.argmax(content) == 0) and (content.std() <= 50):
        return 'LM'
    elif (np.argmax(content) == 1) and (content.std() < 50):
        return 'LMH'
    elif (np.argmax(content) == 1) and (content.std() > 50):
        if content[0] > content[2]:
            return 'LM'
        else:
            return 'MH'
    if (np.argmax(content) == 2) and (content.std() > 50):
        return 'H'
    elif (np.argmax(content) == 2) and (content.std() <= 50):
        return 'MH'
        
def pH_numtocat(pH_num):
    if pH_num < 6.1:
        return 'A'
    elif pH_num <= 6.6:
        return 'AN'
    elif pH_num <= 7.3:
        return 'ANB'
    elif pH_num <= 7.8:
        return 'NB'
    else:
        return 'B'

def score_get(row,hardiness,moisture,heaviness,pH):
    Hardiness = (abs(row['UK Hardiness'] - hardiness) / hardiness) 
    Soil = similar(row['Soil'],heaviness)
    Moisture = similar(row['Moisture'],moisture)
    PH = similar(row['pH'],pH)
    return Hardiness+Soil+Moisture+PH
        
        
@app.route('/attrib', methods=['GET'])
@cross_origin()
def api_all():
    lat = request.args.get('lat', type = float)
    lon = request.args.get('lon', type = float)
    lat_ = str(lat)
    lon_ = str(lon)
    
    try:
        url_rain = "https://climateknowledgeportal.worldbank.org/api/data/get-download-data/projection/mavg/pr/rcp26/2020_2039/"+lat_+"$cckp$"+lon_+"/"+lat_+"$cckp$"+lon_
        url_temp = "https://climateknowledgeportal.worldbank.org/api/data/get-download-data/projection/mavg/tas/rcp26/2020_2039/"+lat_+"$cckp$"+lon_+"/"+lat_+"$cckp$"+lon_
        resp_temp = pd.read_csv(url_temp)
        resp_rain = pd.read_csv(url_rain)
        resp_temp = resp_temp['Monthly Temperature - (Celsius)'].mean()
        resp_rain = resp_rain['Monthly Precipitation - (MM)'].mean()
        hardiness = temp_to_hard(resp_temp)
        moisture = rainfall_to_moisture(resp_rain)
        resp_soil = requests.get("http://rest.isric.org/soilgrids/v2.0/properties/query?lon=73&lat=33&property=bdod&property=cec&property=cfvo&property=clay&property=nitrogen&property=ocd&property=ocs&property=phh2o&property=sand&property=silt&property=soc&depth=30-60cm&value=mean").json()
        soil_feature = pd.DataFrame([soil_value(i) for i in resp_soil['properties']['layers']])
        sand = soil_feature[soil_feature.name == 'sand']['value'].values[0]
        silt = soil_feature[soil_feature.name == 'silt']['value'].values[0]
        clay = soil_feature[soil_feature.name == 'clay']['value'].values[0]
        heaviness = content_to_heavy([sand, silt, clay])
        pH = pH_numtocat(soil_feature[soil_feature.name == 'phh2o']['value'].values[0])
         
        cnx = sqlite3.connect('plants_db.db')
        df = pd.read_sql_query("""SELECT "Latin name","Common name","Habit","Family","UK Hardiness","Soil","Moisture","pH","Medicinal","Range",
        "Habitat","Cultivation details","Uses notes","Propagation" FROM plants_details where "UK Hardiness" = {} or "Soil"
         = "{}" or "Moisture" = "{}" or "pH" = "{}" """.format(hardiness,heaviness,moisture,pH),cnx)
        cnx.close()
        
        df['score'] = df[['UK Hardiness','Soil','Moisture','pH']].apply(score_get,axis=1, args=(hardiness,moisture,heaviness,pH))
        df = df.sample(frac=1).reset_index(drop=True)
        out = df.sort_values(by=['score'],ascending=False).head(10)
        
        return out.to_json(orient = 'records')
    except Exception as e:
        return str(e)
 
@app.route('/search', methods=['GET'])
@cross_origin()
def search_name():
    name = request.args.get('name', type = str) 
    try:
        cnx = sqlite3.connect('plants_db.db')
        df = pd.read_sql_query("""SELECT * FROM plants_details""",cnx)
        cnx.close()
        df["fuzz"] = df['Common name'].apply(fuzz_search, args=([name]))
        df = df.sample(frac=1).reset_index(drop=True)
        out = df.sort_values(by=['fuzz'],ascending=False).head(3)
        return out.to_json(orient = 'records')
    except Exception as e:
        return str(e)
if __name__ == '__main__':
    app.run()
