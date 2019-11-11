#!/usr/bin/env python
# coding: utf-8

# In[139]:


import pandas as pd
import json
import datetime


# In[140]:


rh_path = '/Users/val/q5/researchhub-backend/'


# In[141]:


# https://www.kaggle.com/theriley106/university-statistics
# Data was grabbed from US-News: https://www.usnews.com
raw_us_df = pd.read_json(rh_path + 'schoolInfo.json', orient='columns')


# In[142]:


raw_world_df = pd.read_csv(rh_path + 'timesData.csv')


# In[143]:


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


# In[144]:


def remove_columns_from_us_df(raw):
    for col in us_exclude_fields:
        raw.pop(col)
    return raw


# In[145]:


cleaned_us_df = remove_columns_from_us_df(raw_us_df)
cleaned_us_df = cleaned_us_df.drop_duplicates(subset=['displayName'])
cleaned_us_df = cleaned_us_df.sort_values(by=['displayName'])
cleaned_us_df


# In[146]:


cleaned_world_df = raw_world_df.drop_duplicates(subset=['university_name'])
cleaned_world_df = cleaned_world_df.sort_values(by=['university_name'])
cleaned_world_df


# In[147]:


def orient_df_to_index(df):
    return pd.read_json(df.to_json(), orient='index')


# In[148]:


oriented_us_df = orient_df_to_index(cleaned_us_df)
oriented_world_df = orient_df_to_index(cleaned_world_df)


# In[149]:


def convert_world_school(school):
    item = {}
    item['name'] = school['university_name'].strip()
    item['country'] = school['country'].strip()
    return item


# In[150]:


def convert_us_school(school):
    item = {}
    item['name'] = school['displayName'].strip()
    item['city'] = school['city'].strip()
    item['state'] = school['state'].strip()
    return item


# In[151]:


converted_us_schools = [
    convert_us_school(oriented_us_df[i]) for i in oriented_us_df
]
converted_world_schools = [
    convert_world_school(oriented_world_df[i]) for i in oriented_world_df
]


# In[152]:


len(converted_us_schools), len(converted_world_schools)


# In[153]:


def merge_schools(us=converted_us_schools, world=converted_world_schools):
    merged_on_name = []
    hits = 0

    for w in world:
        hit = 0

        for u in us:
            if w['name'] == u['name']:
                hit = 1
                hits += hit

                # merge
                d = u
                d['country'] = w['country']

                merged_on_name.append(d)
                del us[us.index(u)]
                break  # should be no more hits on w

        if hit == 0:
            merged_on_name.append(w)

    remaining_us_schools = us
    print('hits', hits)
    print('merged_on_name', len(merged_on_name))
    print('remaining_us_schools', len(remaining_us_schools))

    return merged_on_name + remaining_us_schools


# In[154]:


def sort_on_name(school):
    return school['name']


# In[155]:


merged_schools = merge_schools(
    us=converted_us_schools,
    world=converted_world_schools
)
merged_schools.sort(key=sort_on_name)


# In[156]:


len(merged_schools)


# In[157]:


def convert_to_fixture(schools):
    fixture = []
    for s in schools:
        item = {}
        item['pk'] = schools.index(s) + 10
        item['model'] = 'user.University'
        item['fields'] = s
        item['fields']['created_date'] = str(
            datetime.datetime.now(tz=datetime.timezone.utc)
        )
        item['fields']['updated_date'] = str(
            datetime.datetime.now(tz=datetime.timezone.utc)
        )
        fixture.append(item)
    return fixture


# In[158]:


fixture = convert_to_fixture(merged_schools)
len(fixture), fixture


# In[159]:


with open('university_fixture.json', 'w') as f:
    json.dump(fixture, f)


# In[ ]:
