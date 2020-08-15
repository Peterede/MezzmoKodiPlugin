import sys
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import os
import xml.etree.ElementTree
import re
import xml.etree.ElementTree as ET
import urlparse
import browse
import linecache
import contentrestriction
import media
import time
import datetime
import socket

syncoffset = 400
addon = xbmcaddon.Addon()

def updateTexturesCache(contenturl):     # Update Kodi image cache timers
  
    try:
        from sqlite3 import dbapi2 as sqlite
    except:
        from pysqlite2 import dbapi2 as sqlite
                      
    DB = os.path.join(xbmc.translatePath("special://database"), "Textures13.db")
    db = sqlite.connect(DB)

    rfpos = contenturl.find(':',7)      #  Get Mezzmo server info
    serverport = '%' + contenturl[rfpos+1:rfpos+6] + '%'
    newtime = (datetime.datetime.now() + datetime.timedelta(days=-3)).strftime('%Y-%m-%d %H:%M:%S')
    cur = db.execute('UPDATE texture SET lasthashcheck=? WHERE URL LIKE ? and lasthashcheck=?', \
    (newtime, serverport, ""))          # Update Mezzmo image cache timers with no dates 
    rows = cur.rowcount       
    db.commit()
    db.close()
    xbmc.log('Mezzmo textures cache timers '  + str(rows) + ' rows updated.', xbmc.LOGNOTICE)   


def deleteTexturesCache(contenturl):        # do not cache texture images if caching disabled
    if addon.getSetting('caching') == 'false':    
        try:
            from sqlite3 import dbapi2 as sqlite
        except:
            from pysqlite2 import dbapi2 as sqlite
                      
        DB = os.path.join(xbmc.translatePath("special://database"), "Textures13.db")
        db = sqlite.connect(DB)

        rfpos = contenturl.find(':',7)      #  Get Mezzmo server info
        serverport = '%' + contenturl[rfpos+1:rfpos+6] + '%'
        cur = db.execute('DELETE FROM texture WHERE url LIKE ?', (serverport,))        
        rows = cur.rowcount
        xbmc.log('Mezzmo addon texture rows deleted: ' + str(rows), xbmc.LOGNOTICE)
        db.commit()
        db.close()
        addon.setSetting('caching', 'true') # reset back to true after clearing 


def getSeconds(t):
    x = time.strptime(t.split(',')[0],'%H:%M:%S.000')
    td = datetime.timedelta(hours=x.tm_hour,minutes=x.tm_min,seconds=x.tm_sec)
    seconds = int((td.microseconds + (td.seconds + td.days * 24 * 3600) * 10**6) / 10**6)
    if seconds == None:
        seconds = 0
    return seconds


def syncMezzmo(syncurl, syncpin, count):	  #  Sync Mezzmo to Kodi
    global syncoffset
    if addon.getSetting('kodisync') == 'true':    #  Check if enabled
        xbmc.log('Mezzmo sync beginning.', xbmc.LOGNOTICE)
        starttime = time.time()
        clean =  0                                #  Set daily clean flag
        rows = 0

        if int(datetime.datetime.now().strftime('%H')) == 12 and count > 12:
            force = 1
            media.kodiCleanDB(syncurl,force)      #  Clear Kodi database daily
            clean = 1                             #  database cleared. Resync all videos
        if count < 12:   
            addon.setSetting('kodiactor', 'true') #  Enable real time updates on startup  
            addon.setSetting('kodichange', 'true')
            content = browse.Browse(syncurl, 'recent', 'BrowseDirectChildren', 0, 400, syncpin)
            rows = syncContent(content, syncurl, 'recent', syncpin)
        elif clean == 0:                          #  Hourly sync 800 newest
            content = browse.Browse(syncurl, 'recent', 'BrowseDirectChildren', 0, 400, syncpin)
            rows = syncContent(content, syncurl, 'recent', syncpin)
            if rows == None:                      #  Did sync get data from Mezzmo server ?
                rows = 0
                xbmc.log('Mezzmo sync process could not contact the Mezzmo server', xbmc.LOGNOTICE) 
            xbmc.log('Mezzmo sync offset = ' + str(syncoffset), xbmc.LOGDEBUG)  
            if rows == 400 and syncoffset % 400 == 0:
                syncoffset = syncoffset + rows - 400              
                content = browse.Browse(syncurl, 'recent', 'BrowseDirectChildren', syncoffset, 800, syncpin)
                rows1 = syncContent(content, syncurl, 'recent', syncpin)
                if rows1 == None:                 # Sanity check for NULL
                    rows1 = 0
                else:
                    syncoffset = syncoffset + rows1
                rows = rows + rows1
            xbmc.log('Mezzmo sync rows test = ' + str(rows), xbmc.LOGDEBUG)
            if rows % 400 <> 0:                   #  Start back through the Mezzmo database
                syncoffset = 400 
                addon.setSetting('kodiactor', 'false') #  Disable real time updating after full sync
                addon.setSetting('kodichange', 'false')                         
        elif clean == 1:                               #  Sync all daily
            content = browse.Browse(syncurl, 'recent', 'BrowseDirectChildren', 0, 1000, syncpin)
            rows = syncContent(content, syncurl, 'recent', syncpin)
            addon.setSetting('kodiactor', 'false')     #  Disable real time updating after full sync
            addon.setSetting('kodichange', 'false')   
        endtime = time.time()
        duration = endtime-starttime
        difference = str(int(duration // 60)) + 'm ' + str(int(duration % 60)) + 's checked.'
        xbmc.log('Mezzmo sync completed. ' + str(rows) + ' videos in ' + difference, xbmc.LOGNOTICE) 
    else:
        xbmc.log('Mezzmo sync is disabled. ', xbmc.LOGNOTICE) 


def syncContent(content, syncurl, objectId, syncpin):  # Mezzmo data parsing / insertion function
    contentType = 'movies'
    itemsleft = -1
        
    try:
        while True:
            e = xml.etree.ElementTree.fromstring(content)
            
            body = e.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Body')
            browseresponse = body.find('.//{urn:schemas-upnp-org:service:ContentDirectory:1}BrowseResponse')
            result = browseresponse.find('Result')
            NumberReturned = browseresponse.find('NumberReturned').text
            TotalMatches = browseresponse.find('TotalMatches').text
            if not TotalMatches:                       #  Sanity check
                TotalMatches = 0
            #xbmc.log('Mezzmo total matches = ' + str(TotalMatches), xbmc.LOGNOTICE)             
            if NumberReturned == 0:
                break; #sanity check
                
            if itemsleft == -1:
                if int(NumberReturned) < 1000:
                    TotalMatches = NumberReturned
                    itemsleft = int(NumberReturned)
                else:
                    itemsleft = int(TotalMatches)

            elems = xml.etree.ElementTree.fromstring(result.text.encode('utf-8'))
            
            for container in elems.findall('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}container'):
                title = container.find('.//{http://purl.org/dc/elements/1.1/}title').text 
                containerid = container.get('id')
                
                description_text = ''
                description = container.find('.//{urn:schemas-upnp-org:metadata-1-0/upnp/}longDescription')
                if description != None and description.text != None:
                    description_text = description.text
    
                icon = container.find('.//{urn:schemas-upnp-org:metadata-1-0/upnp/}albumArtURI')
                if icon != None:
                    icon = icon.text
                    if (icon[-4:]) !=  '.jpg': 
                        icon = icon + '.jpg'
                    xbmc.log('Handle browse initial icon is: ' + icon, xbmc.LOGDEBUG)             

            dbfile = media.openKodiDB()                   #  Open Kodi database
            for item in elems.findall('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}item'):
                title = item.find('.//{http://purl.org/dc/elements/1.1/}title').text
                itemid = item.get('id')
                icon = None
                albumartUri = item.find('.//{urn:schemas-upnp-org:metadata-1-0/upnp/}albumArtURI')
                if albumartUri != None:
                    icon = albumartUri.text  
                    if (icon[-4:]) !=  '.jpg': 
                        icon = icon + '.jpg'
                    xbmc.log('Handle browse second icon is: ' + icon, xbmc.LOGDEBUG)    

                res = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}res')
                subtitleurl = None
                duration_text = ''
                video_width = 0
                video_height = 0
                aspect = 0.0
                validf = 0
                
                if res != None:
                    itemurl = res.text 
                    #xbmc.log('The current URL is: ' + itemurl, xbmc.LOGNOTICE)
                    subtitleurl = res.get('{http://www.pv.com/pvns/}subtitleFileUri')            
                    duration_text = res.get('duration')
                    if duration_text == None:
                        duration_text = '00:00:00.000'
                    resolution_text = res.get('resolution')
                    if resolution_text != None:
                        mid = resolution_text.find('x')
                        video_width = int(resolution_text[0:mid])
                        video_height = int(resolution_text[mid + 1:])
                        aspect = float(float(video_width) / float(video_height))
                        validf = 1	     #  Set valid file info flag
                        
                backdropurl = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}cvabackdrop')
                if backdropurl != None:
                    backdropurl = backdropurl.text
                    if (backdropurl [-4:]) !=  '.jpg': 
                        backdropurl  = backdropurl  + '.jpg'
                                   
                trailerurl = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}trailer')
                if trailerurl != None:
                    trailerurl = trailerurl.text
                
                genre_text = ''
                genre = item.find('.//{urn:schemas-upnp-org:metadata-1-0/upnp/}genre')
                if genre != None:
                    genre_text = genre.text
                    
                aired_text = ''
                aired = item.find('.//{http://purl.org/dc/elements/1.1/}date')
                if aired != None:
                    aired_text = aired.text
                  
                album_text = ''
                album = item.find('.//{urn:schemas-upnp-org:metadata-1-0/upnp/}album')
                if album != None:
                    album_text = album.text
                  
                release_year_text = ''
                release_year = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}release_year')
                if release_year != None:
                    release_year_text = release_year.text
                
                description_text = ''
                description = item.find('.//{urn:schemas-upnp-org:metadata-1-0/upnp/}longDescription')
                if description != None and description.text != None:
                    description_text = description.text
                      
                imageSearchUrl = ''
                imageSearchUrl = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}imageSearchUrl')
                if imageSearchUrl != None:
                    imageSearchUrl = imageSearchUrl.text
                   
                artist_text = ''
                artist = item.find('.//{urn:schemas-upnp-org:metadata-1-0/upnp/}artist')
                if artist != None:
                    artist_text = artist.text.encode('utf-8', 'ignore')

                actor_list = ''
                cast_dict = []    # Added cast & thumbnail display from Mezzmo server
                cast_dict_keys = ['name','thumbnail']
                actors = item.find('.//{urn:schemas-upnp-org:metadata-1-0/upnp/}artist')
                if actors != None:
                    actor_list = actors.text.encode('utf-8', 'ignore').replace(', Jr.' , ' Jr.').replace(', Sr.' , ' Sr.').split(',')
                    for a in actor_list:                  
                        actorSearchUrl = imageSearchUrl + "?imagesearch=" + a.lstrip().replace(" ","+")
                        #xbmc.log('search URL: ' + actorSearchUrl, xbmc.LOGNOTICE)  # uncomment for thumbnail debugging
                        new_record = [ a.strip() , actorSearchUrl]
                        cast_dict.append(dict(zip(cast_dict_keys, new_record)))

                creator_text = ''
                creator = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}creator')
                if creator != None:
                    creator_text = creator.text
                    
                lastplayed_text = ''
                lastplayed = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}lastplayed')
                if lastplayed != None:
                    lastplayed_text = lastplayed.text
                   
                tagline_text = ''
                tagline = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}tag_line')
                if tagline != None:
                    tagline_text = tagline.text
                    
                categories_text = 'movie'
                categories = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}categories')
                if categories != None and categories.text != None:
                    categories_text = categories.text.split(',')[0]   #  Kodi can only handle 1 media type
                    if categories_text == 'TV show':
                        categories_text = 'episode'
                        contentType = 'episodes'
                    elif categories_text == 'Movie':
                        categories_text = 'movie'
                        contentType = 'movies'
                        album_text = ''
                    else:
                        categories_text = 'video'
                        contentType = 'videos'
                        album_text = ''

                episode_text = ''
                episode = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}episode')
                if episode != None:
                    episode_text = episode.text
                 
                season_text = ''
                season = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}season')
                if season != None:
                    season_text = season.text
                 
                playcount = 0
                playcount_text = ''
                playcountElem = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}playcount')
                
                if playcountElem != None:
                    playcount_text = playcountElem.text
                    playcount = int(playcount_text)
                 
                last_played_text = ''
                last_played = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}last_played')
                if last_played != None:
                    last_played_text = last_played.text
                        
                writer_text = ''
                writer = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}writers')
                if writer != None:
                    writer_text = writer.text
                       
                content_rating_text = ''
                content_rating = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}content_rating')
                if content_rating != None:
                    content_rating_text = content_rating.text
              
                imdb_text = ''
                imdb = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}imdb_id')
                if imdb != None:
                    imdb_text = imdb.text
                
                
                dcmInfo_text = ''
                dcmInfo = item.find('.//{http://www.sec.co.kr/}dcmInfo')
                if dcmInfo != None:
                    dcmInfo_text = dcmInfo.text
                    valPos = dcmInfo_text.find('BM=') + 3
                    dcmInfo_text = dcmInfo_text[valPos:]
              
                rating_val = ''
                rating = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}rating')
                if rating != None:
                    rating_val = rating.text
                    rating_val = float(rating_val) * 2
                    rating_val = str(rating_val) #kodi ratings are out of 10, Mezzmo is out of 5
                
                production_company_text = ''
                production_company = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}production_company')
                if production_company != None:
                    production_company_text = production_company.text

                sort_title_text = ''
                sort_title = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}sort_title')
                if sort_title != None:
                    sort_title_text = sort_title.text
              
                video_codec_text = ''
                video_codec = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}video_codec')
                if video_codec != None:
                    video_codec_text = video_codec.text
                if video_codec_text == 'vc1':     #  adjust for proper Kodi codec display
                    video_codec_text = 'vc-1'
                
                audio_codec_text = ''
                audio_codec = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}audio_codec')
                if audio_codec != None:
                    audio_codec_text = audio_codec.text
                
                audio_channels_text = ''
                audio_channels = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}audio_channels')
                if audio_channels != None:
                    audio_channels_text = audio_channels.text
                
                audio_lang = ''
                audio_streams = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}audio')
                if audio_streams != None:
                    for stream in audio_streams.findall('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}stream'):
                        if stream.get('selected') == 'auto' or stream.get('selected') == 'true':
                            audio_lang = stream.get('lang')
                            break
                     
                subtitle_lang = ''
                captions_streams = item.find('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}captions')
                if captions_streams != None:
                    for stream in captions_streams.findall('.//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}stream'):
                        if stream.get('selected') == 'auto' or stream.get('selected') == 'true':
                            subtitle_lang = stream.get('language')
                            break

                #mediaClass 
                mediaClass_text = 'video'
                mediaClass = item.find('.//{urn:schemas-sony-com:av}mediaClass')
                if mediaClass != None:
                    mediaClass_text = mediaClass.text
                    if mediaClass_text == 'V':
                        mediaClass_text = 'video'
                    if mediaClass_text == 'M':
                        mediaClass_text = 'music'
                    if mediaClass_text == 'P':
                        mediaClass_text = 'picture'
                          
                tvcheckval = media.tvChecker(season_text, episode_text) # Is TV show and user enabled Kodi DB adding
                if tvcheckval == 1:  
                    mtitle = media.displayTitles(title)
                    pathcheck = media.getPath(itemurl)                  #  Get path string for media file
                    serverid = media.getMServer(itemurl)                #  Get Mezzmo server id
                    filekey = media.checkDBpath(itemurl, mtitle, playcount, dbfile, pathcheck, serverid,        \
                    season_text, episode_text, album_text)
                    #xbmc.log('Mezzmo filekey is: ' + str(filekey), xbmc.LOGNOTICE) 
                    durationsecs = getSeconds(duration_text)            #  convert movie duration to seconds before passing
                    kodichange = 'true'                                 #  Enable change detection during sync
                    if filekey[4] == 1:
                        showId = media.checkTVShow(filekey, album_text, genre_text, dbfile, content_rating_text, \
                        production_company_text)
                        mediaId = media.writeEpisodeToDb(filekey, mtitle, description_text, tagline_text,        \
                        writer_text, creator_text, aired_text, rating_val, durationsecs, genre_text, trailerurl, \
                        content_rating_text, icon, kodichange, backdropurl, dbfile, production_company_text,     \
                        sort_title_text, season_text, episode_text, showId)  
                    else:  
                        mediaId = media.writeMovieToDb(filekey, mtitle, description_text, tagline_text,          \
                        writer_text, creator_text, release_year_text, rating_val, durationsecs, genre_text,      \
                        trailerurl, content_rating_text, icon, kodichange, backdropurl, dbfile,                  \
                        production_company_text, sort_title_text)
                    if (artist != None and filekey[0] > 0) or mediaId == 999999: #  Add actor information to new movie
                        media.writeActorsToDb(artist_text, mediaId, imageSearchUrl, mtitle, dbfile, filekey)
                    media.writeMovieStreams(filekey, video_codec_text, aspect, video_height, video_width,  \
                    audio_codec_text, audio_channels_text, durationsecs, mtitle, kodichange, itemurl,      \
                    icon, backdropurl, dbfile, pathcheck)               # Update movie stream info 
                    #xbmc.log('The movie name is: ' + mtitle.encode('utf-8'), xbmc.LOGNOTICE)
                                                      
            itemsleft = itemsleft - int(NumberReturned)
            xbmc.log('Mezzmo items left: ' + str(itemsleft), xbmc.LOGDEBUG) 
            dbfile.commit()                #  Commit writes

            if itemsleft == 0:
                dbfile.commit()
                dbfile.close()             #  Final commit writes and close Kodi database
                return(int(TotalMatches))  
                break
                        
            # get the next items
            offset = int(TotalMatches) - itemsleft
            requestedCount = 1000
            if itemsleft < 1000:
                requestedCount = itemsleft
            
            pin = addon.getSetting('content_pin')   
            content = browse.Browse(syncurl, objectId, 'BrowseDirectChildren', offset, requestedCount, syncpin)
    except Exception as e:
        printsyncexception()
        pass
        

def printsyncexception():
    exc_type, exc_obj, tb = sys.exc_info()
    f = tb.tb_frame
    lineno = tb.tb_lineno
    filename = f.f_code.co_filename
    linecache.checkcache(filename)
    line = linecache.getline(filename, lineno, f.f_globals)
    xbmc.log( 'EXCEPTION IN ({0}, LINE {1} "{2}"): {3}'.format(filename, lineno, line.strip(), exc_obj))

