#!/usr/bin/env python
# coding: utf-8
# flake8: noqa

# In[1]:


import pandas as pd
import numpy as np
import json
import datetime


# In[2]:


data_path = './.ipynb/'


# In[3]:


# https://www.kaggle.com/theriley106/university-statistics
# Data was grabbed from US-News: https://www.usnews.com
raw_us_df = pd.read_json('https://researchhub-paper-prod.s3-us-west-2.amazonaws.com/schoolInfo.json', orient='columns')


# In[4]:


# https://github.com/Hipo/university-domains-list
raw_world_df = pd.read_json('https://researchhub-paper-prod.s3-us-west-2.amazonaws.com/world_universities_and_domains.json')


# In[5]:


us_exclude_fields = [
    'rankingNoteText',
    'nonResponderText',
    'nonResponder',
    'act-avg',
    'sat-avg',
    'rankingNoteCharacter',
    'acceptance-rate',
    'rankingDisplayScore',
    'percent-receiving-aid',
    'cost-after-aid',
    'rankingSortRank',
    'hs-gpa-avg',
    'rankingDisplayName',
    'rankingDisplayRank',
    'ranking',
    'xwalkId',
    'rankingIsTied',
    'businessRepScore',
    'tuition',
    'aliasNames',
    'rankingType',
    'overallRank',
    'rankingMaxPossibleScore',
    'rankingRankStatus',
    'primaryKey',
    'engineeringRepScore',
    'isPublic',
    'region',
    'schoolType',
    'enrollment',
]


# In[6]:


def remove_columns_from_us_df(raw):
    for col in us_exclude_fields:
        raw.pop(col)
    return raw


# In[7]:


cleaned_us_df = remove_columns_from_us_df(raw_us_df)
cleaned_us_df = cleaned_us_df.drop_duplicates(subset=['displayName'])
cleaned_us_df = cleaned_us_df.sort_values(by=['displayName'])
cleaned_us_df


# In[8]:


cleaned_world_df = raw_world_df.drop_duplicates(subset=['name'])
cleaned_world_df = cleaned_world_df.sort_values(by=['name'])
cleaned_world_df


# In[9]:


def orient_df_to_index(df):
    return pd.read_json(df.to_json(), orient='index')


# In[10]:


oriented_us_df = orient_df_to_index(cleaned_us_df)
oriented_world_df = orient_df_to_index(cleaned_world_df)


# In[11]:


def convert_world_school(school):
    item = {}
    item['name'] = school['name'].strip()
    item['country'] = school['country'].strip()
    return item


# In[12]:


def convert_us_school(school):
    item = {}
    item['name'] = school['displayName'].strip()
    item['city'] = school['city'].strip()
    item['state'] = school['state'].strip()
    return item


# In[13]:


converted_us_schools = [convert_us_school(oriented_us_df[i]) for i in oriented_us_df]
converted_world_schools = [convert_world_school(oriented_world_df[i]) for i in oriented_world_df]


# In[14]:


len(converted_us_schools), len(converted_world_schools)


# In[15]:


def merge_schools(us=None, world=None):
    merged_on_name = []
    hits = 0
    UNITED_STATES = ''

    for w in world:
        hit = 0

        for u in us:
            if w['name'] == u['name']:
                hit = 1
                hits += hit

                # merge
                d = u
                d['country'] = w['country']
                UNITED_STATES = w['country']

                merged_on_name.append(d)
                del us[us.index(u)]
                break  # should be no more hits on w

        if hit == 0:
            merged_on_name.append(w)

    remaining_us_schools = us

    for r in remaining_us_schools:
        r['country'] = UNITED_STATES
        merged_on_name.append(r)

    return merged_on_name


# In[16]:


def sort_on_name(school):
    return school['name']


# In[17]:


merged_schools = merge_schools(us=converted_us_schools, world=converted_world_schools)
merged_schools.sort(key=sort_on_name)


# In[18]:


len(merged_schools)


# In[19]:


def convert_to_fixture(schools):
    fixture = []
    for i, s in enumerate(schools):
        item = {}
        item['pk'] = i + 10
        item['model'] = 'user.University'
        item['fields'] = s
        item['fields']['created_date'] = str(datetime.datetime.now(tz=datetime.timezone.utc))
        item['fields']['updated_date'] = str(datetime.datetime.now(tz=datetime.timezone.utc))
        fixture.append(item)
    return fixture


# In[20]:


fixture = convert_to_fixture(merged_schools)
len(fixture), fixture


# In[21]:


with open('university_fixture.json', 'w') as f:
    json.dump(fixture, f)


# In[ ]:
