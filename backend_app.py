import flask
from flask import request, jsonify
import sqlite3
import pandas as pd
import requests
import numpy as np
from difflib import SequenceMatcher
#from fuzzywuzzy import fuzz
import jellyfish
from flask_cors import CORS, cross_origin


app = flask.Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

app.config["DEBUG"] = True

@app.route("/")
@cross_origin()
def helloWorld():
  return "Hello, cross-origin-world!"

def calc_carbon_tree(height, diameter=25, age = 10):
    """Calculates annual CO2 Sequestration"""
    """Height in meter, diameter in cm, age in years"""
    """This includes habits: Tree, Bamboo"""
    
    #convert to imperial
    height = height/3.281 #feet
    diameter = diameter/2.54 #inches
        
    #calculate green weight of tree: (above-ground weight) * 1.2
    if diameter < 11:
        green_weight = (0.25 * diameter**2 * height) * 1.2
    else:
        green_weight = (0.15 * diameter**2 * height) * 1.2
        
    #dry weight: average tree is 72.5 dry matter    
    dry_weight = 0.725 * green_weight
    
    #weight of carbon: 50% of tree dry weight
    c_weight = 0.5 * dry_weight
    
    #weight of CO2 sequestered
    co2_weight = 3.67 * c_weight
    
    return co2_weight/2.205/age #convert from lbs to kg and divide by age
    
def calc_carbon_shrub(height, age = 3):
    """height in meter"""
    """This includes habits: Shrub, fern"""
    
    
    #approximate a sphere
    #the taller the shrub, the lower its biomass density?
    #get green weight
    
    scaling = 1/height * 25
    volume = 4/3 * np.pi * (height/2)**3
    green_weight = volume * scaling * 1.2

    
    #dry weight: average tree is 72.5 dry matter, shrubs probably aswell    
    dry_weight = 0.725 * green_weight
    
    #weight of carbon: 50% of tree dry weight
    c_weight = 0.5 * dry_weight
    
    #weight of CO2 sequestered
    co2_weight = 3.67 * c_weight
    
    return co2_weight/age #convert from lbs to kg
    
def calc_carbon_herb(height, diameter = 1, age = 1):
    """Calculates lifetime CO2 Sequestration"""
    """This includes habits: perennial, annual, bulb, climber, biennial\
    annual/biennial, perennial climber, annual/perennial, corm, annual climber"""
    
    #convert to imperial
    height /= 3.281 #feet
    diameter /= 2.54 #inches
    
    #print(height, diameter)
    
    #calculate green weight of herb: (above-ground weight) * 1.2
    green_weight = ( diameter**2 * height) * 1.2
            
    #dry weight: average tree is 72.5 dry matter    
    dry_weight = 0.725 * green_weight
    
    #weight of carbon: 50% of tree dry weight
    c_weight = 0.5 * dry_weight
    
    #weight of CO2 sequestered
    co2_weight = 3.67 * c_weight
    
    return co2_weight/2.205/1 #convert from lbs to kg, divide by age
    
def carbon_cal(row):
    height = row['Height']
    habit = row['Habit']
    if habit in ['Tree', 'Bamboo']:
        if height == None:
            return None
        else:
            return calc_carbon_tree(height = height)
    elif habit in ['Shrub', 'Fern']:
        if height == None:
            return None
        else:
            return calc_carbon_shrub(height = height)
        
    elif habit in ['Biennial/Perennial', 'Annual/Perennial', 'Climber',
        'Perennial', 'Annual', 'Bulb', 'Perennial Climber',
       'Biennial', 'Annual/Biennial', 'Corm', 'Annual Climber']:
        if height == None:
            return None
        else:
            return calc_carbon_herb(height = height)
    

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
        return jellyfish.jaro_distance(namecol.lower(),name.lower())
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
        df = pd.read_sql_query("""SELECT "Latin name","Common name","Habit","Height","Family","UK Hardiness","Soil","Moisture","pH","Medicinal","Range",
        "Habitat","Cultivation details","Uses notes","Propagation" FROM plants_details where "UK Hardiness" = {} or "Soil"
         = "{}" or "Moisture" = "{}" or "pH" = "{}" """.format(hardiness,heaviness,moisture,pH),cnx)
        cnx.close()
        
        df['score'] = df[['UK Hardiness','Soil','Moisture','pH']].apply(score_get,axis=1, args=(hardiness,moisture,heaviness,pH))
        df = df.sample(frac=1).reset_index(drop=True)
        out = df.sort_values(by=['score'],ascending=False).head(10)
        out['reduc_in_CO2'] = out.apply(carbon_cal,axis=1)
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
        df["fuzz_c"] = df['Common name'].apply(fuzz_search, args=([name]))
        df["fuzz_l"] = df['Latin name'].apply(fuzz_search, args=([name]))
        df["fuzz_t"] = df["fuzz_l"]+df["fuzz_c"]
        df = df.sample(frac=1).reset_index(drop=True)
        out = df.sort_values(by=['fuzz_t'],ascending=False).head(3)
        out['reduc_in_CO2'] = out.apply(carbon_cal,axis=1)
        return out.to_json(orient = 'records')
    except Exception as e:
        return str(e)
if __name__ == '__main__':
    app.run()
