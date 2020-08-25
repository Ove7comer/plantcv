#### link utilities
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jun  9 09:53:34 2020

Functions used in time series linking after getting leaf instances segmented

@author: hudanyunsheng
"""

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import os
import sys
import random
import math
import skimage.io
import pickle as pkl
import re
from skimage.measure import find_contours
from matplotlib import patches,  lines
from matplotlib.patches import Polygon
from plantcv import plantcv as pcv
import datetime
import copy
import colorsys
from plantcv.plantcv import fatal_error
from scipy.optimize import linear_sum_assignment


def _random_colors(N, bright=True):
    """
    Generate random colors.
    To get visually distinct colors, generate them in HSV space then
    convert to RGB.
    """
    brightness = 1.0 if bright else 0.7
    hsv = [(i / N, 1, brightness) for i in range(N)]
    colors = list(map(lambda c: colorsys.hsv_to_rgb(*c), hsv))
    random.shuffle(colors)
    return colors


def _apply_mask(image, mask, color, alpha=0.5):
    """Apply the given mask to the image.
    """
    for c in range(3):
        image[:, :, c] = np.where(mask == 1,
                                  image[:, :, c] *
                                  (1 - alpha) + alpha * color[c] * 255,
                                  image[:, :, c])
    return image


def display_instances(image, boxes, masks, class_ids, class_names,
                      scores=None, title="",
                      figsize=(16, 16), ax=None,
                      show_mask=True, show_bbox=True,
                      colors=None, captions=None):
    """
    boxes: [num_instance, (y1, x1, y2, x2, class_id)] in image coordinates.
    masks: [height, width, num_instances]
    class_ids: [num_instances]
    class_names: list of class names of the dataset
    scores: (optional) confidence scores for each box
    title: (optional) Figure title
    show_mask, show_bbox: To show masks and bounding boxes or not
    figsize: (optional) the size of the image
    colors: (optional) An array or colors to use with each object
    captions: (optional) A list of strings to use as captions for each object
    """
    # Number of instances
    N = boxes.shape[0]
    if not N:
        print("\n*** No instances to display *** \n")
    else:
        assert boxes.shape[0] == masks.shape[-1] == class_ids.shape[0]

    # If no axis is passed, create one and automatically call show()
    auto_show = False
    if not ax:
        _, ax = plt.subplots(1, figsize=figsize)
        auto_show = True

    # Generate random colors
    colors = colors or _random_colors(N)

    # Show area outside image boundaries.
    height, width = image.shape[:2]
    ax.set_ylim(height + 10, -10)
    ax.set_xlim(-10, width + 10)
    ax.axis('off')
    ax.set_title(title)

    masked_image = image.astype(np.uint32).copy()
    for i in range(N):
        color = colors[i]

        # Bounding box
        if not np.any(boxes[i]):
            # Skip this instance. Has no bbox. Likely lost in image cropping.
            continue
        y1, x1, y2, x2 = boxes[i]
        if show_bbox:
            p = patches.Rectangle((x1, y1), x2 - x1, y2 - y1, linewidth=2,
                                  alpha=0.7, linestyle="dashed",
                                  edgecolor=color, facecolor='none')
            ax.add_patch(p)

        # Label
        if not captions:
            class_id = class_ids[i]
            score = scores[i] if scores is not None else None
            label = class_names[class_id]
            caption = "{} {:.3f}".format(label, score) if score else label
        else:
            caption = captions[i]
        ax.text(x1, y1 + 8, caption,
                color='w', size=11, backgroundcolor="none")

        # Mask
        mask = masks[:, :, i]
        if show_mask:
            masked_image = _apply_mask(masked_image, mask, color)

        # Mask Polygon
        # Pad to ensure proper polygons for masks that touch image edges.
        padded_mask = np.zeros(
            (mask.shape[0] + 2, mask.shape[1] + 2), dtype=np.uint8)
        padded_mask[1:-1, 1:-1] = mask
        contours = find_contours(padded_mask, 0.5)
        for verts in contours:
            # Subtract the padding and flip (y, x) to (x, y)
            verts = np.fliplr(verts) - 1
            p = Polygon(verts, facecolor="none", edgecolor=color)
            ax.add_patch(p)
    ax.imshow(masked_image.astype(np.uint8))
    if auto_show:
        plt.show()

def _compute_overlaps_masks(masks1, masks2):    
    """Computes IoU overlaps between two sets of masks.
    masks1, masks2: [Height, Width, instances]
    mode: 1 or 2, 1 represent for IOU, 2 represent for intersection over the area of the previous mask
    """
    mode = 1
    # If either set of masks is empty return empty result
    if masks1.shape[-1] == 0 or masks2.shape[-1] == 0:
        return np.zeros((masks1.shape[-1], masks2.shape[-1]))
    n1 = masks1.shape[2]
    n2 = masks2.shape[2]
    intersections = np.zeros((n1,n2))
    unions        = np.zeros((n1,n2))
    for idx_m in range(0, n1):
        maski  = np.expand_dims(masks1[:,:,idx_m], axis=2)
        masks_ = np.reshape(masks2 > .5, (-1, masks2.shape[-1])).astype(np.float32)
        maski_ = np.reshape(maski > .5, (-1, maski.shape[-1])).astype(np.float32)
        intersection = np.dot(masks_.T, maski_).squeeze()
        intersections[idx_m,:] = intersection
        union  = np.sum(masks_,0) + np.sum(maski_) - intersection
        unions[idx_m,:] = union
    IOUs = np.divide(intersections,unions)
    return IOUs

def get_ax(rows=1, cols=1, size=16):  # ???
    """Return a Matplotlib Axes array to be used in
    all visualizations in the notebook. Provide a
    central point to control graph sizes.

    Adjust the size attribute to control how big to render images
    """
    fig, ax = plt.subplots(rows, cols, figsize=(size * cols, size * rows))
    fig.tight_layout()
    return ax

class PlantData():
    def __init__(self, imagedir, segmentationdir, savedir, pattern_datetime, suffix='.jpg'):            

        self.suffix = suffix
        self.ext    = None

        self.pattern_datetime = pattern_datetime

        # store a list of time of the images
        self.time = []
        # store a list of original prefixes of the original images
        self.filename_pre = []
        # total num of leaves that being detected
        self.numleaf = 0

        # store all the images
        self.images = []

        # minimum dimension of image. To link time series, all images must have the same dimension, to make it easier, we make the image square
        self.min_dim = 0

        # store all the mask detection during [starttime, endtime]
        self.masks = []

        # store all the rois (for visualization with bounding boxes)
        self.rois = []

        # store all the class_ids (for visualization with bounding boxes)
        self.class_ids = []

        # store all the scores (for visualization with bounding boxes)
        self.scores = []

        # store the dataset directory, instance segmentation result directory, time-series linking result directory and visualization directory
        self.imagedir = imagedir
        self.segmentationdir = segmentationdir
        junk = datetime.datetime.now()

        subfolder = '{}-{}-{}-{}-{}'.format(junk.year, str(junk.month).zfill(2), str(junk.day).zfill(2),
                                            str(junk.hour).zfill(2), str(junk.minute).zfill(2))
        self.savedir = os.path.join(savedir, subfolder)
        if not os.path.exists(self.savedir):
            os.makedirs(self.savedir)

        self.visualdir = os.path.join(self.savedir, 'visualization')

        self.total_time = 0
        self.max_nleaf = 0
        self.init_nleaf = 0
        self.num_leaves = []
        self.num_emergence = 0

        self.emerging_info = []  # list length: self.total_time
        self.link_info = []  # list length: self.total_time-1, dictionaries inside
        self.weights = []  # list length: self.total_time-1, dictionaries inside
        self.available_leaves = []  # list length: self.total_time
        self.link_series = dict()  # only for those newly emerging leaves

    def getinitleaf(self):
        self.init_nleaf = self.masks[0].shape[2]

    def getmaxleaf(self):
        for i in range(0, len(self.masks)):
            self.num_leaves.append(self.masks[i].shape[2])
        self.max_nleaf = np.max(self.num_leaves)

    def gettotaltime(self):
        # also represent for the total number of images
        self.total_time = len(self.time)

    def getnumemergence(self):
        self.num_emergence = np.ones((self.total_time), dtype=int) * self.init_nleaf
        self.num_emergence[1:] = np.diff(self.num_leaves)

    def getpath(self, path):
        self.dir = path

    def Sorttime(self, time_cond):
        """
           This function is designed for files with file names which contain a "date-time" part, with an user-defined pattern, e.g. YYYY-MM-DD-hh-mm
           Return: loop through the dataset_dir, and add time in time order
        """

        filenames = [f for f in os.listdir(self.segmentationdir) if f.endswith('.pkl')]
        filenames_ori = [f for f in os.listdir(self.imagedir) if f.endswith(self.suffix)]
        time_temp = []
        file_name = []
        ext1, ext2 = os.path.splitext(self.suffix)
        if ext1.startswith('.'):
            self.ext = ext1
        elif ext2.startswith('.'):
            self.ext = ext2
        for filename in filenames:
            temp = re.search(self.pattern_datetime, filename)
            if temp:
                timepart = temp.group()
                for cond in time_cond:
                    if timepart.endswith(cond):
                        time_temp.append(timepart)
                        junk = [1 if re.search(timepart, f) is not None else 0 for f in filenames_ori]
                        file_name.append(filenames_ori[junk.index(1)].replace(self.ext, ''))
                        continue

        index_temp = np.argsort(time_temp)
        # forward
        self.time = [time_temp[i] for i in index_temp]
        self.filename_pre = [file_name[i] for i in index_temp]

    def load_images(self):
        """ Load original images
            This function is also designed for files with file names which contain a "date-time" part, with a user defined pattern
        """
        temp_imgs = []
        sz = []
        for pre in self.filename_pre:
            filename = pre + '.jpg'
            junk = skimage.io.imread(os.path.join(self.imagedir, filename))
            temp_imgs.append(junk)
            sz.append(np.min(junk.shape[0:2]))
        self.min_dim = np.min(sz)
        for junk in temp_imgs:
            img = junk[0: self.min_dim, 0: self.min_dim, :]  # make all images the same size
            self.images.append(img)

    def load_results(self):
        """ Instead of running instance segmentation, load instance segmentation results (masks)
        """
        for t in self.time:
            file_name = '{}.pkl'.format(t)
            r = pkl.load(open(os.path.join(self.segmentationdir, file_name), 'rb'))
            self.masks.append(r["masks"][0: self.min_dim, 0: self.min_dim, :])  # make all masks the same size
            self.rois.append(r["rois"])
            self.class_ids.append(r['class_ids'])
            self.scores.append(r['scores'])

    def initialize_linking(self):
        self.emerging_info    = [[] for i in range(0, self.total_time)]
        self.link_info        = [-np.ones((self.num_leaves[i]), dtype=int) for i in range(0, self.total_time - 1)]
        self.weights          = [-np.inf * np.ones((self.num_leaves[i], self.num_leaves[i + 1])) for i in range(0, self.total_time - 1)]
        self.available_leaves = [np.array(range(0, self.num_leaves[i])) for i in range(0, self.total_time)]
        self.time_compare     = [np.ones((self.num_leaves[i]), dtype=int) * i for i in range(0, self.total_time)]

    def linking(self, t0):
        threshold = 0.2
        masks0 = copy.deepcopy(self.masks[t0])
        masks1 = copy.deepcopy(self.masks[t0 + 1])
        leaves0 = copy.deepcopy(self.available_leaves[t0])
        leaves1 = copy.deepcopy(self.available_leaves[t0 + 1])
        n0 = len(leaves0)
        n1 = len(leaves1)
        n  = np.min((n0, n1))
        N  = np.max((n0, n1))
        weight = -np.inf * np.ones((n0, n1))
        link = -np.ones((n0))           
        weight = _compute_overlaps_masks(masks0, masks1)
        idx_col = np.where(np.max(weight, axis=0) < threshold)[0] # find those volumns with maximum value < 0.15
        avail_col = [x for x in range(0,n1) if x not in idx_col]
        weight_ = copy.deepcopy(weight)

        weight_ = np.delete(weight_, idx_col, 1) 
        row_ind, col_ind = linear_sum_assignment(weight_, maximize=True)
        for (r, c) in zip(row_ind, col_ind):
            if weight_[r, c] >= threshold:
                link[r] = avail_col[c]
        self.link_info[t0] = link

    def get_series(self):
        ## define new leaves and their unique identifiers at time points with new leaves emerging
        t = 0
        key_t = 't{}'.format(t)
        self.link_series[key_t] = dict()
        self.link_series[key_t]['new_leaf'] = self.available_leaves[0]
        #
        self.link_series[key_t]['unique_id'] = self.link_series[key_t]['new_leaf']
        unique_id = len(self.link_series[key_t]['new_leaf'])

        for t in range(1, self.total_time):
            #         for t in range(1, self.total_time-1):
            new_leaves = [i for i in self.available_leaves[t] if i not in self.link_info[t - 1]]
            if new_leaves:
                key_t = 't{}'.format(t)
                self.link_series[key_t] = dict()
                self.link_series[key_t]['new_leaf'] = np.array(new_leaves)

                id_temp = []
                for new_leaf in new_leaves:
                    id_temp.append(unique_id)
                    unique_id = unique_id + 1
                self.link_series[key_t]['unique_id'] = np.array(id_temp)
        ## for time points with new leaves emerging, get the linking information for every new leaf
        for key_t in self.link_series:
            t0 = int(key_t.replace('t', ''))  
            for leaf in self.link_series[key_t]['new_leaf']:
                key_leaf = 'leaf{}'.format(leaf)
                self.link_series[key_t][key_leaf] = -np.ones(self.total_time, dtype=int)
                self.link_series[key_t][key_leaf][t0] = leaf
                if t0 < self.total_time - 1:
                    self.link_series[key_t][key_leaf][t0 + 1] = self.link_info[t0][leaf]
                    for t_ in range(t0 + 2, self.total_time):
                        idx = self.link_series[key_t][key_leaf][t_ - 1]
                        if idx < 0:
                            break
                        else:
                            self.link_series[key_t][key_leaf][t_] = self.link_info[t_ - 1][idx]
                            