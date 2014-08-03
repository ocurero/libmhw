#!/usr/bin/python
import linuxdvb
import fcntl
import time
import sys
from binascii import hexlify
import xmltv
import unicodedata
from datetime import datetime

#convert string to hex
def toHex(s):
    lst = []
    for ch in s:
        hv = hex(ord(ch)).replace('0x', '')
        if len(hv) == 1:
            hv = '0'+hv
        lst.append(hv)
    return reduce(lambda x,y:x+y, lst)

def SetFilterSection(fd, pid, tid):

    fcntl.ioctl(fd, linuxdvb.DMX_SET_BUFFER_SIZE, 188*1024)
    parama=linuxdvb.dmx_sct_filter_params()
    parama.pid=pid
    parama.timeout=60000
    parama.flags= linuxdvb.DMX_IMMEDIATE_START
    parama.filter.filter[0]=tid
    parama.filter.mask[0]=0xFF
    fcntl.ioctl(fd, linuxdvb.DMX_SET_FILTER, parama)


def GetTableLen(header):
    return (ord(header[2]) | ( ord(header[1]) & 0x0f) << 8 )  
    #3 first reserved bytes not counted!

def GetDoub(chars):
    return (ord(chars[0]) << 8) | ord(chars[1])

def GetChannels(data):
    num_channels = ord(data[120])
    #print "Found %d channels" % (num_channels,)
    channels = []
    offset_start = num_channels * 8 + 121
    for num in range(num_channels):
        channel_name_length = ord(data[offset_start]) & 0x0f
        channels.append(data[offset_start + 1:offset_start + 1 + channel_name_length].decode("ISO-8859-15"))
        offset_start=offset_start + 1 + channel_name_length 
    return channels

def GetCategories(data):
    data=data[3:]
    num_cat = ord(data[1])
    #print "Found %d categories" % (num_cat,)
    categories = []
    for i in range(num_cat):
        ind_cat = (ord(data[i*2+2]) << 8 ) + ord(data[i * 2 + 3])
        num_cat_sub = (ord(data[ind_cat]) & 0x3f ) + 1
        sub_categories = []
        for j in range(num_cat_sub):
            ind_str = (ord(data[ind_cat + 1 + j * 2]) << 8) + ord(data[ind_cat + 2 + j * 2])
            length_cat = ord(data[ind_str]) & 0x1f;
            sub_categories.append(data[ind_str + 1: ind_str + 1 + length_cat].decode("ISO-8859-15"))
       
        categories.append(sub_categories)
    return categories

def GetTitles(data, data_length, channels, categories):
    offset_start=18
    programs=[]
    category_id = ord(data[7]) & 0xf
    category = categories[category_id][0]
    while offset_start < data_length:
        channel_num = ord(data[offset_start])
        offset_start += 7
        airtime = (GetDoub(data[offset_start + 4:offset_start + 6]) - 40587) * 86400\
            + (((ord(data[offset_start + 6]) & 0xf0) >> 4) * 10 + (ord(data[offset_start + 6]) & 0x0f)) * 3600\
            + (((ord(data[offset_start + 7]) & 0xf0) >> 4) * 10 + (ord(data[offset_start + 7]) & 0x0f)) * 60
        length = (GetDoub(data[offset_start + 9:offset_start + 11]) >>4)
        title_length = ord(data[offset_start + 11]) & 0x3f;
        title = data[offset_start + 12:offset_start + 12 + title_length].decode("ISO-8859-15")
        offset_start += title_length + 12
        sub_category_id = (ord(data[offset_start]) & 0x3f)
        sub_category = categories[category_id][sub_category_id]
        program_id = GetDoub(data[offset_start + 1:offset_start + 3])
        programs.append({"category": category, "subcategory": sub_category, "channel":channels[channel_num],\
        "airtime":airtime, "length":length, "title":title, "id": program_id})
        offset_start += 3 # 10
    return programs    

def GetSummaries(data):
    summary_id = GetDoub(data[3:5])
    nb = ord(data[14])
    offset_start = 15 + nb
    if len(data) > ord(data[14]) + 17: 
        nb=ord(data[offset_start]) & 0x0f
        summary_id = GetDoub(data[3:5]);
        offset_start += 1
        summary_length = 0
        summary=""
        lines=[]
        while nb > 0: 
            line_length = ord(data[offset_start  + summary_length])
            lines.append(line_length)
            summary+=data[offset_start + 1:offset_start + line_length + 1] + "@"
            offset_start=offset_start + line_length + 1
            nb-=1
        offset = 0
        summary_text=""
        for line in lines:
            summary_text += summary[offset:offset + line] + " "
            offset = offset + line + 1
        return (summary_id, summary_text.decode("ISO-8859-15"))

class NoMHWStreamFoundError(Exception): 
    def __init__(self):
        pass
    def __str__(self):
        return "No MHW stream found on the current channel"

class Programme:
    def __init__(self, title, channel, airtime, summary, category, subcategory):
        self.title = title
        self.channel = channel
        self.airtime = airtime
        self.category = category
        self.subcategory = subcategory

class MHW:
    def __init__(self, device, mhw_version=2):
        self.device = open(device, 'r+')
        self.channels = []
        self.programs = []

    def scan_stream(self):
        summary_list = {}
        title_list = []
        programs = []
        SetFilterSection(self.device, 561, 200)
        try:
            buffer = self.device.read(4)
        except:
            raise NoMHWStreamFoundError()
        if len(buffer) == 4:
            #print "MHWv2 stream found!"
            while True:
                table_len = GetTableLen(buffer)
                table_data = "".join(buffer) + self.device.read(table_len - 1)
                #
                # GetChannels
                #
                if hexlify(buffer[0]) == "c8" and hexlify(buffer[3]) == "00" and len(self.channels) == 0:
                    self.channels = GetChannels(table_data)
                #
                # GetCategories
                #
                elif hexlify(buffer[0]) == "c8" and hexlify(buffer[3]) == "01":
                    self.categories = GetCategories(table_data)
                    if len(self.channels) > 0:
                        SetFilterSection(self.device, 564, 230)
                #
                # GetTitles
                #
                elif hexlify(buffer[0]) == "e6":
                    header = (ord(table_data[3]) << 24) | (ord(table_data[4]) << 16) | (ord(table_data[5]) << 8)\
                    | ord(table_data[6])
                    if len(title_list) == 0:
                        start_packet = header
                    else:
                        if header == start_packet:
                            #print "Found " + str(len(title_list)) + " programs"
                            SetFilterSection(self.device, 566, 150)
                    title_list+=GetTitles(table_data, table_len, self.channels, self.categories)
                    
                #
                # GetSummaries
                #
                elif hexlify(buffer[0]) == "96": #96
                    header = (ord(table_data[3]) << 24) | (ord(table_data[4]) << 16) | (ord(table_data[5]) << 8)\
                    | ord(table_data[6])
                    if len(summary_list) == 0:
                        start_packet = header
                    else:
                        if header == start_packet:
                            #print "Found " + str(len(summary_list.keys())) + " descriptions"
                            break
                    if hexlify(table_data[6]) != "01":
                        summary = GetSummaries(table_data)
                        summary_list[summary[0]] = summary[1]
                        
                buffer=self.device.read(4)
        for title in title_list:
            if summary_list.has_key(title["id"]):
                summary = summary_list[title["id"]]
            else:
                summary = u""
        
            programs.append(Programme(title["title"], title["channel"], datetime.fromtimestamp(title["airtime"]),\
            summary, title["category"], title["subcategory"]))
        return (self.channels, programs)
