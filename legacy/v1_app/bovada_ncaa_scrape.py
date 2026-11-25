#%% Section 1
# necessary import for getting
# directory and filenames
import os
from bs4 import BeautifulSoup

# Get current working directory
#directory = 'V://bovada-master//Bovada_Pages//'
directory = 'C://Users//JTB Ventures LLC//OneDrive//Gambling//Daily_Lines//'
ilename = 'Bet on College Basketball Odds & Lines _ Bovada Sportsbook 11.14.22.html'

#%% Section 2
# for all the files present in that
# directory
#for filename in os.listdir(directory):
	
	# check whether the file is having
	# the extension as html and it can
	# be done with endswith function
	#if filename.endswith('.html'):
		
	# os.path.join() method in Python join
	# one or more path components which helps
	# to exactly get the file

fname = os.path.join(directory, filename)
print("Current file name ..", os.path.abspath(fname))
		
# open the file
with open(fname, 'r') as file:
		
	beautifulSoupText = BeautifulSoup(file.read(), 'html.parser')
			
	# parse the html as you wish
	#for tag in beautifulSoupText.findAll(True):
	#	print(tag.name, " : ", len(beautifulSoupText.find(tag.name).text))
#%%section 3
teamTag = beautifulSoupText.find_all("bx-site")

home_teams = []
away_teams = []
for tag in teamTag:
    team = tag.find_all("span", {"class": "name"})
    i = 1
    for tag in team:
        if (i % 2 != 1):        
            print("home team: " + tag.text)
            home_teams.append(tag.text)
        else:
            print("away team: " + tag.text)
            away_teams.append(tag.text)
        i = i+1
        
#%%section 4
spreadTag = beautifulSoupText.find_all("sp-spread-outcome")

home_line = []
away_line = []
i = 1  
for tag in spreadTag:
    line = tag.find_all("span", {"class": "market-line bet-handicap"})
    for tag in line:
        if (i % 2 != 1):        
            print("home line: " + tag.text)
            home_line.append(tag.text)
        else:
            print("away line: " + tag.text)
            away_line.append(tag.text)
        i = i+1
        
#%%section 5
soTag = beautifulSoupText.find_all("bx-site")

home_spread_price = []
away_spread_price = []
home_moneyline = []
away_moneyline = []
home_ou_price = []
away_ou_price = []

i = 1  
for tag in soTag:
    line = tag.find_all("span", {"class": "bet-price"})
    for tag in line:
        if (i % 6 == 1):        
            print( "away spread price: " + tag.text)
            away_spread_price.append(tag.text)
        elif (i % 6 == 2): 
            print( "home spread price: " + tag.text)
            home_spread_price.append(tag.text)
        elif (i % 6 == 3): 
            print( "away moneyline: " + tag.text)
            away_moneyline.append(tag.text)
        elif (i % 6 == 4): 
            print( "home moneyline: " + tag.text)
            home_moneyline.append(tag.text)
        elif (i % 6 == 5): 
            print( "away OU price: " + tag.text)
            away_ou_price.append(tag.text)
        else: #6th option --> i % 6 == 0
            print( "home OU price: " + tag.text)
            home_ou_price.append(tag.text)
        i = i+1
        

        
#%%section 7 - Over/Under
home_ou = []
away_ou = []

soTag = beautifulSoupText.find_all("bx-site")

i = 1  
for tag in soTag:
    line = tag.find_all("span", {"class": "market-line bet-handicap both-handicaps"})
    for tag in line:
        ou = tag.text.replace(' (R)','').replace(' (L)','')
        if (i % 2 == 1):        
            print( "away ou: " + ou)
            away_ou.append(ou)
        elif (i % 2 == 0): 
            print( "home ou: " + ou)
            home_ou.append(ou)
        i = i+1
        
#%%manually remove values from lists, if needed   
'''
away_line2 = home_moneyline.remove( ' +8.0 ')  
home_moneyline_price2 = home_moneyline.remove( ' +180 ')   
away_moneyline2 = away_moneyline.remove( ' -220 ') 
home_spread_price2 = home_spread_price.remove( ' +200 ')   
away_spread_price2 = away_spread_price.remove( ' -245 ') 
away_teams2 = away_teams.remove('Away Total Runs') 
home_teams2 = home_teams.remove('hOME Total Runs')  
'''
'''
away_pitcher2 = away_pitcher.remove('Average')  
home_pitcher2 = home_pitcher.remove('Average') 
'''
'''#run when grand salami is present
away_pitcher2 = away_pitcher.append('Grand')  
home_pitcher2 = home_pitcher.append('Salami') 
'''

'''#insert blank pitchers when games already started 
away_pitcher2 = ['average']
home_pitcher2 = ['average']
away_pitcher = away_pitcher2  + away_pitcher
home_pitcher = home_pitcher2 + home_pitcher

away_line.append('trash')  
home_line.append('trash')  
away_ou_price.append('Average') 
home_ou_price.append('Average') 
'''
#%%section 8 - final output        
num_games = len(home_teams)    
#if bovada displays the "home vs. away runs bet, iterate -1 step to adjust for mlb games that day
#num_games = len(home_teams)-1  
print( num_games)


csvlines = ''
comma = ','
linebrk = '\r\n'
slash = '/'

print('number of games: ' + str(num_games))
for i in range(num_games):
    currline = away_teams[i]+comma+home_teams[i]+comma+comma+comma+away_spread_price[i]+slash+home_spread_price[i]+comma+away_line[i]+comma+away_moneyline[i]+comma+home_moneyline[i]+comma+away_ou[i]+comma+away_ou_price[i]+slash+home_ou_price[i]+linebrk
    currline.replace('(','').replace(')','')    
    csvlines = csvlines + currline
print(csvlines)