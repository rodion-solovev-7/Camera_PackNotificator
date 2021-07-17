import numpy as np
import cv2, time, os

import requests

#import RecogModule as rc
from datetime import datetime, timedelta

from tensorflow.keras import models
import tensorflow as tf

import RecogModule as rc     
                            
#net = models.load_model('X2com.h5')


state_url = 'http://10.14.2.21/api/v1_0/get_mode'
url = 'http://10.14.2.21/api/v1_0/new_pack_after_pintset'
#url = 'http://141.101.196.128/api/v1_0/new_pack_after_pintset'

#converter = tf.lite.TFLiteConverter.from_keras_model(net)
#tflite_model = converter.convert()

#with open('XCEPT.tflite', 'wb') as f:
#  f.write(tflite_model)
  
interpreter = tf.lite.Interpreter(model_path="old/XCEPT.tflite")
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

#video_url = 'rtsp://admin:admin@10.14.2.37:554/1/1'
video_url = '../81465-video.mp4'
#video_url = '/home/sergey/AFE/XPS.DEV/5/11/6573/6573-video.mp4'
#video_url = '/home/sergey/AFE/XPS.DEV/4/1812/6952/6952-video.mp4'

last_bc = '0000000000000'

video = cv2.VideoCapture(video_url)
#video = cv2.VideoCapture('755-video.mp4')
ww = video.get(cv2.CAP_PROP_FRAME_WIDTH)
hh = video.get(cv2.CAP_PROP_FRAME_HEIGHT)

success = False
packflag = False

i=0
ans = ['Фон','Пачка']
fin_qr = ''
fin_bc = ''

maxFC = 150

buff = []
fastB = []
bc, qr = '', ''
wmode = 'auto'

while (True):

    ret, frame = video.read()
        
    if ret:
	
        frame2 = cv2.resize(frame,(853, 480))
        cv2.imshow('frame',frame2)
	
        #Сохраняю картинки в буфер
        buff.append(frame2)
        if len(buff) > maxFC:
            buff = buff[1:]
	
        if i%15 == 0:
                   
            # получаю прогноз сетью, как опция - опрашиваю датчик
            i = 1       
            t0 = time.time()		
            rgb_image = cv2.resize(frame,(248,136))
            rgb_image = cv2.cvtColor(rgb_image, cv2.COLOR_BGR2RGB)
           		
           
            rgb_image = np.expand_dims(rgb_image, axis = 0)
            img = rgb_image.astype('float32')/255
            
            try:
                interpreter.set_tensor(input_details[0]['index'], img)
                interpreter.invoke()
                pred = interpreter.get_tensor(output_details[0]['index']) 
                
       #         if pred[0][0] > 0.5:
       #             print ('пачка')
       #         else:
       #             print ('fon')    
                    
                 
            except:
                pass
	
        i += 1
        
        if pred[0][0] > 0.5: # Вижу пачку ищу коды пока не найду или пачка не кончится
            
            packflag = True
            if not success:
                bc, qr = rc.dummy_codes ([frame], ww, hh, 0.4)  
                
            if (fin_qr == '') and (qr != ''):
                fin_qr = qr          
        
            if (fin_bc == '') and (bc != ''):
                fin_bc = bc          
        
        
            if (fin_qr != ''):# and (fin_bc != ''):
                success = True    
            
        else:  # вижу фон
            
            if packflag:  # только что была пачка подводим итоги     
                if not success:
                    print ('Blue story')
                    
                    # Записываю картинки на диск / не нашел хотя бы один код
                    try: 
                        pass
                    #    resp = requests.get(state_url, timeout = 2)
                    #    wmode = resp.json()['work_mode']
                    except:
                        wmode = 'auto'
                             
            
                    if wmode == 'auto': # проверяю автоматичность режима для записи
                    
                        try:
                            dt = datetime.now()
                            folder_name = '/home/ftpuser/events/pics/'+dt.strftime("%Y-%m-%d_%H-%M-%S.%f")[:-3]
                           # os.makedirs(folder_name)

                        #    for j, frame in enumerate(buff):
                        #        cv2.imwrite(f'{folder_name}/{j}.jpg', frame)
                        except:
                            pass        
                                  
                
                
                
                buff = []
                
                print (fin_qr)
                print (fin_bc)
                
                if fin_bc != '':
                    fin_bc = bytes.decode(fin_bc)
                    last_bc = fin_bc
                else:
                    fin_bc = last_bc    
     
                if fin_qr != '':
                    fin_qr = bytes.decode(fin_qr)
                else:
                    a = datetime.now()
                    s = a.strftime('%x - %X')
                    fin_qr = 'empty '+ s
                    fin_bc = '0000000000000'       


                dat = { "qr": fin_qr,
                    "barcode":fin_bc
                    }
                
                try:
                    pass
    #                response = requests.put(url, json=dat, timeout = 2)
                except:
                    print ('Аппликатор  - нет Сети')
                
                
                a = datetime.now()
                s = a.strftime('%x - %X')                    
                    
                f = open ('old/Xcam1_log.txt', 'a')
                f.write (s+','+ fin_bc+','+fin_qr+'\n' )
                f.close()
                
                bc, qr = '', ''
                packflag = False
                success = False
                
                fin_qr = ''
                fin_bc = ''
                           
        		
    else:
        print ('Пустой кадр')
        
        video.release()
        video = cv2.VideoCapture(video_url)        


    inn = cv2.waitKey(1) & 0xFF	
    if inn == ord('q'):
        break


    
    

video.release()
cv2.destroyAllWindows()

