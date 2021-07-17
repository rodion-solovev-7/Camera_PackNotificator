"""
Created on Sat Jun  6 12:29:01 2020

@author: sergey
"""
import tensorflow as tf
from tensorflow.keras import models
import cv2
from pyzbar.pyzbar import decode
import numpy as np
from tensorflow.keras.preprocessing import image


# ****************************************************************************
# возвращает наиболее часто повторяющийся элемент словаря
# и не пустой )))
# ****************************************************************************
def get_friquent (ans):

    mn = ''
    
    if len(ans) > 0:
        aa = {}
        mm = 0
   
        for k in range(len(ans)):
            
            if ans[k]!='':
                
                if ans[k] in aa.keys():
                    aa[ans[k]] += 1
                else:
                    aa[ans[k]] = 1
                      
            
                if aa[ans[k]] > mm:
                    mm = aa[ans[k]]
                    mn = ans[k]

    return mn
 

#----------------------------------------------------------------------------

# *****************************************************************************
# возвращает ШК с серии снимков
# Наводится на ШК нейросетью
# *****************************************************************************
def get_bc_from_loc (pics):
    
    
    ans = []
    
    
    for j in range(len(pics)):
        
        img = cv2.resize(pics[j],(Pic_X,Pic_Y))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = np.expand_dims(img, axis = 0)
        
        reg = regs.predict(img)

        reg = np.reshape(reg, (mat_Y, mat_X))
        m, n = np.where(reg > 0.6)
        
        if len(m)>0:
           
           # un,co=np.unique(m,return_counts=True)
            
            x1, y1 = int(round(n.min()*div_X/Sizer_X*2.25)), int(round(m.min()*div_Y/Sizer_Y*2.25))
            x2, y2 = int(round((n.max()+1)*div_X/Sizer_X*2.25)), int(round((m.max()+1)*div_Y/Sizer_Y*2.25))
           
            
           
            #x1, y1 = int(round(n.min()*div_X/Sizer_X*2.25)), int(round(un[i]*div_Y/Sizer_Y*2.25))
            #x2, y2 = int(round((n.max()+1)*div_X/Sizer_X*2.25)), int(round((un[i]+1)*div_Y/Sizer_Y*2.25))        
            codePict = pics[j][y1:y2,x1:x2,:]
            
            # Бинаризация
            #codePict = cv2.cvtColor(codePict, cv2.COLOR_BGR2GRAY)
            #mid = codePict.mean()
            #ret,codePict = cv2.threshold(codePict,mid,255,cv2.THRESH_BINARY)
            
            #cv2.imwrite('2/tratata_'+str(j)+'.jpg',codePict)
            try:
                
                # Бинаризация
                codePict = cv2.cvtColor(codePict, cv2.COLOR_BGR2GRAY)
                mid = codePict.mean()
                ret,codePict = cv2.threshold(codePict,mid,255,cv2.THRESH_BINARY)

                code = decode(codePict)
                s=str(code[0][0])
                ans.append(s[2:-1])
                #print(s[2:-1])
                
            except:
                pass
             

    return get_friquent (ans)
        
# *******************************************************************************

# *****************************************************************************
# возвращает ШК с серии снимков
# ШК берет из указанного ROI
# *****************************************************************************

def get_bc_from_ROI (pics, x1, y1, x2, y2, sizer):
    
    
    ans = []
    
    
    for j in range(len(pics)):
        
        codePict = pics[j][y1:y2,x1:x2,:]
            
            # Бинаризация
        codePict = cv2.cvtColor(codePict, cv2.COLOR_BGR2GRAY)
        mid = codePict.mean()
        ret,codePict = cv2.threshold(codePict,mid,255,cv2.THRESH_BINARY)
        
        if sizer != 1:
            newX = int(round((x2-x1)*sizer))
            newY = int(round((y2-y1)*sizer))
            
            codePict = cv2.resize(codePict,(newX,newY))
            
        #cv2.imwrite('2/tratata_'+str(j)+'.jpg',codePict)
        try:
                
            code = decode(codePict)
            s=str(code[0][0])
            ans.append(s[2:-1])
                #print(s[2:-1])
                
        except:
            pass
             

    return get_friquent (ans)


# *******************************************************************************


# *****************************************************************************
#  тупо возвращает ШК и QR с серии снимков
# *****************************************************************************

def dummy_codes (pics, ww, hh, sizer):
    
    QRs = []
    BCs = []
    
    for pic in pics:
        newX = int(round(ww*sizer))
        newY = int(round(hh*sizer))
        
        #pic = cv2.cvtColor(pic, cv2.COLOR_BGR2RGB)

        sized = cv2.resize(pic, (newX,newY))
        codePict = cv2.cvtColor(sized, cv2.COLOR_BGR2GRAY)        
        ret,codePict = cv2.threshold(codePict,100,255,cv2.THRESH_BINARY)

        code = decode(codePict)

        for lss in code:
            
            if lss.type == 'QRCODE':
                QRs.append(lss.data)
            else:
                BCs.append(lss.data)
                
    QR = get_friquent(QRs)        
    BC = get_friquent(BCs)
    
  #  print (len(QRs), len(BCs))
    
    if len(BC) < 13:
        BC = ''
        
    return BC, QR    
                
# *******************************************************************************

# *****************************************************************************
#  тупо возвращает ШК и QR с серии картинок jpeg
# *****************************************************************************

def dummy_pics (pics, ww, hh, sizer):
    
    QRs = []
    BCs = []
    
    for pic in pics:
        newX = int(round(ww*sizer))
        newY = int(round(hh*sizer))
        
        #pic = cv2.cvtColor(pic, cv2.COLOR_BGR2RGB)

        sized = cv2.resize(pic, (newX,newY))
        
        sized = image.array_to_img(sized)
        #codePict = cv2.cvtColor(sized, cv2.COLOR_BGR2GRAY)        
        #ret,codePict = cv2.threshold(codePict,127,255,cv2.THRESH_BINARY)

        code = decode(sized)

        for lss in code:
            
            if lss.type == 'QRCODE':
                QRs.append(lss.data)
            else:
                BCs.append(lss.data)
                
    QR = get_friquent(QRs)        
    BC = get_friquent(BCs)
    
 #   print (len(QRs), len(BCs))
        
    return BC, QR    



# *****************************************************************************
#  тупо возвращает ШК и QR с одного снимка
# *****************************************************************************

def dummy_codes_one (pic, ww, hh, sizer):
    
    BC, QR = '',''
    #pic = cv2.cvtColor(pic, cv2.COLOR_BGR2RGB)
    newX = int(round(ww*sizer))
    newY = int(round(hh*sizer))
    
    sized = cv2.resize(pic, (newX,newY))
    #codePict = cv2.cvtColor(sized, cv2.COLOR_BGR2GRAY)        
    #ret,codePict = cv2.threshold(codePict,127,255,cv2.THRESH_BINARY)

    code = decode(sized)

    for lss in code:
            
        if lss.type == 'QRCODE':
            QR = lss.data
        else:
            BC = lss.data
                
        
    return BC, QR    
                

# Определяем метрику и функцию потерь
def iou_loss_core(true, pred):  #this can be used as a loss if you make it negative
    intersection = true * pred
    notTrue = 1 - true
    union = true + (notTrue * pred)

    return tf.keras.backend.sum(intersection) / tf.keras.backend.sum(union)

def iou_loss(y_true, y_pred):
    return -iou_loss_core(y_true, y_pred) 


Or_X, Or_Y = 853, 480  # Размеры исходного изображения

Pic_X = 320   # Размеры картинки - входа НС
Pic_Y = 240

mat_Y, mat_X = 26, 36  # Размер матрицы выхода НС

div_X = Pic_X / mat_X  # Делители - преобразователи координат картинки в координвты матрицы 
div_Y = Pic_Y / mat_Y

Sizer_X = Pic_X/Or_X   # Масштабаторы картинки и картинки входа - для пересчета координат разметки.
Sizer_Y = Pic_Y/Or_Y

#regs = models.load_model('OMNY_YOLO_8549.h5',custom_objects={'iou_loss': iou_loss, 'iou_loss_core': iou_loss_core})       
