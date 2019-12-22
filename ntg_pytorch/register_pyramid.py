import cv2
import scipy.misc as smi
import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn.functional as F


def compute_pyramid(image_batch,f,nL,ration):

    image_batch = image_batch.transpose(1,2).transpose(2,3)

    image_batch = image_batch.numpy()
    multi_level_image_batch = []
    multi_level_image_batch.append(image_batch.transpose((0,3,1,2)))
    current_ration = ration
    for level in range(1,nL):

        level_image_batch = []
        for image_item in image_batch:
            tmp = cv2.filter2D(image_item,-1,f)
            level_image = smi.imresize(tmp,size=current_ration)/255.0

            if len(level_image.shape) == 2:
                level_image = level_image[:,:,np.newaxis]
            level_image_batch.append(level_image)

        level_image_batch = np.array(level_image_batch).transpose((0,3,1,2))



        multi_level_image_batch.append(level_image_batch)
        current_ration = current_ration * ration


    return multi_level_image_batch



class ScaleTnf:
    def __init__(self):
        self.theta_identity = torch.tensor([
            [1, 0, 0],
            [0, 1, 0]
        ], dtype=torch.float).unsqueeze(0)      #[batch,2,3]

    def __call__(self,image_batch, ration):

        batch_size, c, h, w = image_batch.size()
        out_size = torch.Size((batch_size, c, int(h * ration), int(w * ration)))
        grid = F.affine_grid(self.theta_identity.repeat(batch_size,1,1), out_size)
        output = F.grid_sample(image_batch, grid)
        return output

def compute_pyramid_pytorch(image_batch,scaleTnf,filter,nL,ration):
    '''
    :param image_batch: [batch,channel,h,w]  Tensor
    :param f:
    :param nL:
    :param ration:
    :return:
    '''

    kernel = torch.Tensor(filter).unsqueeze(0).unsqueeze(0)

    multi_level_image_batch = []
    multi_level_image_batch.append(image_batch)
    for level in range(1,nL):
        image_batch = F.conv2d(image_batch, kernel, padding=1)

        image_batch = scaleTnf(image_batch,ration)

        multi_level_image_batch.append(image_batch)

    return multi_level_image_batch



