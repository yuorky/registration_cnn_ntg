import cv2
import numpy as np
import torch
import matplotlib.pyplot as plt
import torch.nn.functional as F
import torch.nn as nn

from tnf_transform.transformation import affine_transform_pytorch, affine_transform_opencv, \
    affine_transform_opencv_batch
from traditional_ntg.loss_function import deriv_filt
from util.pytorchTcv import param2theta

def ntg_gradient_torch(objdict,p,use_cuda = False):
    options = objdict['parser']
    source_image_batch = objdict['source_images']
    target_image_batch = objdict['target_images']

    p_pytorch = param2theta(p, source_image_batch.shape[2], source_image_batch.shape[3], use_cuda=use_cuda)
    warpI = affine_transform_pytorch(source_image_batch, p_pytorch)

    # 结果不如使用pytorch的
    # warpI = affine_transform_opencv_batch(source_image_batch,p,use_cuda=use_cuda)

    batch, c, h, w = source_image_batch.shape

    # I_source_x,I_source_y = deriv_filt_pytorch(source_image_batch, False, use_cuda)
    # Ipx = affine_transform_opencv_batch(I_source_x,p,use_cuda=use_cuda)
    # Ipy = affine_transform_opencv_batch(I_source_y,p,use_cuda=use_cuda)

    # Ipx = affine_transform_pytorch(I_source_x,p_pytorch)
    # Ipy = affine_transform_pytorch(I_source_y,p_pytorch)

    # 直接使用变换图像的梯度不如使用梯度图进行变换精度高
    Ipx, Ipy = deriv_filt_pytorch(warpI, False, use_cuda)
    It = warpI - target_image_batch

    J = compute_ntg_pytorch(target_image_batch, warpI, use_cuda)

    [Itx, Ity] = deriv_filt_pytorch(It, False, use_cuda)

    rho_x = func_rho_pytorch(Itx, 1,use_cuda= use_cuda) - J.reshape(batch,1,1,1) * func_rho_pytorch(Ipx, 1,use_cuda= use_cuda)
    rho_y = func_rho_pytorch(Ity, 1,use_cuda= use_cuda) - J.reshape(batch,1,1,1) * func_rho_pytorch(Ipy, 1,use_cuda= use_cuda)

    [wxx, wxy] = deriv_filt_pytorch(rho_x, True, use_cuda)
    [wyx, wyy] = deriv_filt_pytorch(rho_y, True, use_cuda)

    w = wxx + wyy

    # w = w.squeeze()
    g = torch.zeros((p.shape[0],6, 1))
    if use_cuda:
        g = g.cuda()
    g[:,0] = torch.mean(w * objdict['X_array'] * Ipx,(2,3))
    g[:,1] = torch.mean(w * objdict['Y_array'] * Ipx,(2,3))
    g[:,2] = torch.mean(w * Ipx,(2,3))
    g[:,3] = torch.mean(w * objdict['X_array'] * Ipy,(2,3))
    g[:,4] = torch.mean(w * objdict['Y_array'] * Ipy,(2,3))
    g[:,5] = torch.mean(w * Ipy,(2,3))

    g = g.reshape(-1, 2, 3)

    return g

def compute_ntg_pytorch(img1,img2,use_cuda=True):
    g1x, g1y = deriv_filt_pytorch(img1,False,use_cuda= use_cuda)
    g2x, g2y = deriv_filt_pytorch(img2,False,use_cuda= use_cuda)

    # g1xy = torch.sqrt(torch.pow(g1x,2)+torch.pow(g1y,2))
    # g2xy = torch.sqrt(torch.pow(g2x,2)+torch.pow(g2y,2))

    m1 = func_rho_pytorch(g1x - g2x, 0,use_cuda= use_cuda) + func_rho_pytorch(g1y - g2y, 0,use_cuda= use_cuda)
    n1 = func_rho_pytorch(g1x, 0,use_cuda= use_cuda) + func_rho_pytorch(g2x, 0,use_cuda= use_cuda) + \
         func_rho_pytorch(g1y, 0,use_cuda= use_cuda) + func_rho_pytorch(g2y, 0,use_cuda= use_cuda)
    y1 = m1 / (n1 + 1e-16)

    #print(y1)
    return y1

def deriv_filt_pytorch(I,isconj,use_cuda=False):
    '''
    :param I: 输入维度为Tensor [batch_size,channel,h,w]
    :param isconj:
    :return:
    '''
    # I = I.squeeze().numpy()
    # Ix,Iy = deriv_filt(I,isconj)
    # Ix = torch.Tensor(Ix).unsqueeze(0).unsqueeze(0)
    # Iy = torch.Tensor(Iy).unsqueeze(0).unsqueeze(0)
    #
    # return Ix,Iy

    batch,channel,h,w = I.shape
    if not isconj:
        kernel_x = [[-0.5,0,0.5]]
        kernel_y = [[-0.5],[0],[0.5]]
    else:
        kernel_x = [[0.5,0,-0.5]]
        kernel_y = [[0.5],[0],[-0.5]]

    kernel_x = torch.Tensor(kernel_x).unsqueeze(0)
    kernel_y = torch.Tensor(kernel_y).unsqueeze(0)

    kernel_x = kernel_x.expand(channel,1,kernel_x.shape[1],kernel_x.shape[2])
    kernel_y = kernel_y.expand(channel,1,kernel_y.shape[1],kernel_y.shape[2])

    if use_cuda:
        kernel_x = kernel_x.cuda()
        kernel_y = kernel_y.cuda()

    ## 注意，这里面的Ix和Iy和cv2的filter不一样
    # Ix = F.conv2d(I,kernel_x,padding=1)[:,:,1:-1,:] # 上下为0
    # Iy = F.conv2d(I,kernel_y,padding=1)[:,:,:,1:-1] # 左右为0

    # I = F.pad(I,(1,1,1,1),mode='reflect')
    # Ix = F.conv2d(I,kernel_x,padding=0)[:,:,1:-1,:] # 上下为0
    # Iy = F.conv2d(I,kernel_y,padding=0)[:,:,:,1:-1] # 左右为0


    ## 注意！不同的mode导致的结果也不一样
    # 这里的groups是使用了分组卷积，相当于使用每个channel对滤波核进行操作，加了以后能够处理多通道如RGB图片
    # 和cv2.filter2D不一样，这里的直接就是计算，没有后续处理。
    # 按照0填充,这个和opencv的filter2D的处理方式一样
    # Ix_pad = F.pad(I,(1,1,0,0),mode='replicate')
    # Iy_pad = F.pad(I,(0,0,1,1),mode='replicate')

    Ix_pad = F.pad(I,(1,1,0,0),mode='reflect')
    Iy_pad = F.pad(I,(0,0,1,1),mode='reflect')


    Ix = F.conv2d(Ix_pad,kernel_x,padding=0,groups=channel) # 上下为0
    Iy = F.conv2d(Iy_pad,kernel_y,padding=0,groups=channel) # 左右为0


    # 这个pad操作很影响最后的结果
    # Ix = F.pad(Ix,(1,1,0,0),mode='reflect')
    # Iy = F.pad(Iy,(0,0,1,1),mode='reflect')


    # Ix = torch.max(Ix,torch.Tensor([0]))
    # Iy = torch.max(Iy,torch.Tensor([0]))

    # Ix = F.pad(Ix,(1,1,0,0),mode='circular')
    # Iy = F.pad(Iy,(0,0,1,1),mode='circular')

    return Ix,Iy


def func_rho_pytorch(x,order,epsilon=0.01,use_cuda=False):
    if use_cuda:
        epsilon = torch.Tensor([epsilon]).float().cuda()
    else:
        epsilon = torch.Tensor([epsilon]).float()
    if order == 0:
        y = torch.sqrt(torch.pow(x, 2) + torch.pow(epsilon, 2))
        y = torch.sum(y.reshape(x.shape[0], -1), 1)
    elif order == 1:
        y = x / torch.sqrt(torch.pow(x, 2) + torch.pow(epsilon, 2))

    return y
