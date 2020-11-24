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
raw_us_df = pd.read_json('https://storage.googleapis.com/kagglesdsdata/datasets/10525/14746/schoolInfo.json?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Credential=gcp-kaggle-com%40kaggle-161607.iam.gserviceaccount.com%2F20201124%2Fauto%2Fstorage%2Fgoog4_request&X-Goog-Date=20201124T021632Z&X-Goog-Expires=259199&X-Goog-SignedHeaders=host&X-Goog-Signature=062f04e0f608efcd78058f2bc06d9e6c9e432ac0994ef2352c432fe3a625218d987862e59aa37067b1b055a004299f26109765356e4e76d59a1a015e21877e076f5b54dc81f00f3e06b249a3783f9640bff71bdf17361f46bde31f0a20d7148910e650a596694dfb47edaa0c1f5f382b358fd363b8f195209a936247487c6ed838aa78d4a519da5b64afb02ced56071080e259f40d24f6a4d64f18195257e3c04103d290dd017b1c3cc2e0857389ae965fd9f4edee8af0d42b8cb1a1fd765f1e391173c47d4bf6a0c84d6fa079be0ebfdbab89a0d218e4ccfc2e6086d4632fed761816322b3e9d44bbd5d7e70b4ab39583e0579de39a108770f05792cc92dfc6', orient='columns')


# In[4]:


# https://github.com/Hipo/university-domains-list
raw_world_df = pd.read_json('https://raw.githubusercontent.com/Hipo/university-domains-list/master/world_universities_and_domains.json')


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
