from __future__ import print_function
from apiclient.discovery import build
from httplib2 import Http as http
from oauth2client import file, client, tools
from iso8601 import parse_date as parsedt
from rfc3339 import rfc3339    as printdt
from random import randint
import numpy as np
from skopt import dummy_minimize as minimizer

class Mapping:
  def __init__(self,shiftcal,cals):
    self.map    = [np.nan for i in shiftcal.events]
    self.shifts = shiftcal.events
    self.cals   = cals

  def print_map(self):
    for s,m in zip(self.shifts,self.map):
      print('{:>16} -> {:<16}'.format(s.name,self.cals[m].name))

  def set_map(self,map):
    self.map = map
    return self

  def score(self):
    return \
        001.*self.score_prefs()   \
      + 010.*self.score_balance() \
      + 100.*self.score_overlap()

  def score_overlap(self):
    J = 0.0
    for c in self.cals:
      J += -len(c.get_overlaps())
    return J

  def score_balance(self):
    return -np.var([self.map.count(i) for i in range(len(self.cals))])

  def score_prefs(self):
    J = 0.0
    for s,m in zip(self.shifts,self.map):
      if (m >= 0) and (m < len(self.cals)):
        for e in self.cals[m].events:
          if s.during(e):
            J += e.score
      else:
        J += -np.infty
    return J

  def apply(self):
    for s,m in zip(self.shifts,self.map):
      self.cals[m].add_event(s)

class Calendar:
  def __init__(self,calDict,window=None):
    self.id      = calDict['id']
    self.name    = calDict['summary']
    self.window  = window if window is not None else default_window()
    self.events  = self.get_events()

  def get_events(self):
    return [Event(e) for e in \
            calapi.events().list(calendarId=self.id,
                                 timeMin=printdt(self.window.start),
                                 timeMax=printdt(self.window.end))
                                 .execute()['items']]
  def add_window(self,window):
    self.window = window
    self.events = [e for e in self.events if e.during(window)]

  def add_event(self,event):
    eventDict = event.dict
    eventDict.pop('organizer')
    calapi.events().import_(calendarId=self.id,body=eventDict).execute()
    self.events += [event]

  def get_overlaps(self):
    overlaps = []
    for i in range(len(self.events)):
      for j in range(i):
        if self.events[i].overlap(self.events[j]):
          overlaps += [(i,j)]
    return overlaps

class Event:
  def __init__(self,eventDict):
    self.id    = eventDict['id']
    self.name  = eventDict['summary']
    self.start = parsedt(eventDict['start']['dateTime'])
    self.end   = parsedt(eventDict['end']  ['dateTime'])
    self.score = self.get_score()
    self.dict  = eventDict

  def length(self):
    return self.end - self.start

  def get_score(self):
    if self.name == 'request-off':
      return -100.0
    elif self.name == 'avoid':
      return -1.0
    elif self.name == 'prefer':
      return +1.0
    else:
      return 0.0

  def overlap(self,event):
    return not(
      ((self.start - event.end).total_seconds() > 0) or \
      ((event.start - self.end).total_seconds() > 0))

  def during(self,event):
    return \
      ((self.start - event.start).total_seconds() >= 0) and \
      ((self.end   - event.end  ).total_seconds() <= 0)

def default_window(calapi=None):
  return Event({
    'id': None,
    'summary': 'default window',
    'start': {'dateTime': '2000-01-01T00:00:00+00:00'},
    'end':   {'dateTime': '2050-01-01T00:00:00+00:00'}
  })

def openapi():
  scope = 'https://www.googleapis.com/auth/calendar'
  store = file.Storage('credentials.json')
  creds = store.get()
  if not creds or creds.invalid:
    flow  = client.flow_from_clientsecrets('client_secret.json', scope)
    creds = tools.run_flow(flow, store)
  return build('calendar','v3',http=creds.authorize(http()))

def keypop(objects,key,value,popped=None):
  if popped is None:
    popped = []
  try:
    popped.append(objects.pop([o[key] for o in objects].index(value)))
    popped = keypop(objects,key,value,popped)
  except:
    pass
  return popped

def get_cals(window=None):
  def exclude(c):
    return \
      bool('primary' in c and c['primary']) or \
      bool(c['summary'] == 'shifts')
  return [Calendar(c,window) for c in \
          calapi.calendarList().list().execute()['items']
          if not exclude(c)]

def init_minimizer(shiftcal,cals):
  map  = Mapping(shiftcal,cals)
  return {
    'func':       lambda x: -objective(map,x),
    'dimensions': [(0,len(cals))          for i in range(len(map.shifts))],
    'x0':         [randint(0,len(cals)) for i in range(len(map.shifts))],
    'n_calls':    1000,
    'callback':   jprint,
  }

def jprint(res):
  print('[ {:>5} ] J = {:>6.1f}'.format(len(res.func_vals),res.fun))

def objective(map,x):
  return map.set_map(x).score()

calapi   = openapi()
shiftcal = Calendar(keypop(calapi.calendarList().list().execute()['items'],'summary','shifts')[0])
window   = shiftcal.events.pop([e.name for e in shiftcal.events].index('window'))
shiftcal.add_window(window)

cals = get_cals(window=window)
res  = minimizer(**init_minimizer(shiftcal,cals))
map  = Mapping(shiftcal,cals).set_map(res.x)
print('-'*36)
map.print_map()
print('-'*36)
# map.apply()
