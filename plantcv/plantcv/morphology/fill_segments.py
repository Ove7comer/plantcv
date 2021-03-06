import os
import cv2
import numpy as np
from skimage.segmentation import watershed
from plantcv.plantcv import fatal_error
from plantcv.plantcv import outputs
from plantcv.plantcv import color_palette
from plantcv.plantcv import params
from plantcv.plantcv import plot_image
from plantcv.plantcv import print_image


def fill_segments(mask, objects):
    """Fills masked segments from contours.

    Inputs:
    mask         = Binary image, single channel, object = 1 and background = 0
    objects      = List of contours

    Returns:
    filled_img   = Filled mask

    :param mask: numpy.ndarray
    :param object: list
    :return filled_img: numpy.ndarray
    """

    params.device += 1

    h,w = mask.shape
    markers = np.zeros((h,w))

    labels = np.arange(len(objects)) + 1
    for i,l in enumerate(labels):
        cv2.drawContours(markers, objects, i ,int(l) , 5)

    # Fill as a watershed segmentation from contours as markers
    filled_mask = watershed(mask==0, markers=markers,
                            mask=mask!=0,compactness=0)

    # Count area in pixels of each segment
    ids, counts = np.unique(filled_mask, return_counts=True)
    outputs.add_observation(variable='segment_area', trait='segment area',
                            method='plantcv.plantcv.morphology.fill_segments',
                            scale='pixels', datatype=list,
                            value=counts[1:].tolist(),
                            label=(ids[1:]-1).tolist())

    rgb_vals = color_palette(num=len(labels), saved=True)
    filled_img = np.zeros((h,w,3), dtype=np.uint8)
    for l in labels:
        for ch in range(3):
            filled_img[:,:,ch][filled_mask==l] = rgb_vals[l-1][ch]

    if params.debug == 'print':
        print_image(filled_img, os.path.join(params.debug_outdir, str(params.device) + '_filled_img.png'))
    elif params.debug == 'plot':
        plot_image(filled_img)

    return filled_img
