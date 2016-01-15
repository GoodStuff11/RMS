

####
# TO DO:
# - analyze results and find hot pixels ("stars" which don't move through the night), hold a record of 
#   hot pixels and apply the correction on subsequent star extractions

###

import time
import sys
import os
import cv2
from skimage import feature, data
import matplotlib.pyplot as plt
import numpy as np
import scipy.optimize as opt

import skimage.morphology as morph
import skimage.exposure as skie

# RMS imports
from RMS.Formats import FFbin


def maskBright(img, global_mean, max_abs_chunk_intensity=80, divider=16):
    """ Masks too bright parts of the image so that star extraction isn't performed on them. Image is divided
        into 16x16 chunks and their mean intensity is checked. If it is too bright, it will be masked by the
        image's mean value.

    @param img: [ndarray] image on which to perform the masking
    @param global_mean: [float] mean value of the given image

    @param max_abs_chunk_intensity: [int] threshold intensity for the chunk (about it it will be masked)
    @param divider: [int] size of the chunks (should be a common divisor of image width and height)
    """

    # Generate indices for subdivision
    x_range = np.arange(0, ff.ncols, divider)
    y_range = np.arange(0, ff.nrows, divider)
    x_range[0] = 0
    y_range[0] = 0

    img_copy = np.copy(img)

    global_std = np.std(img_copy)

    for x in x_range:
        for y in y_range:

            # Extract image segment
            img_chunk = ff.avepixel[y : y+divider, x : x+divider]

            # Calcuate mean value of the segment
            chunk_mean = np.mean(img_chunk)

            # Check if the image sigment is too bright
            if (chunk_mean > global_mean  + 1.3 * global_std or chunk_mean > max_abs_chunk_intensity):
                img_copy[y : y+divider, x : x+divider] = global_mean

    return img_copy


def extractStars(ff, max_global_intensity=80, max_stars=50, star_threshold=0.6):
    """ Extracts stars on a given FF bin by searching for local maxima. 

    @param ff: [ff bin struct] FF bin file loaded in the FF bin structure

    @param max_global_intensity: [int] maximum mean intensity of an image before it is discared as too bright
    @param max_stars: [int] maximum number of stars to be returned by the local maxima detection algorithm
    @param star_threshold: [float] a threshold for cutting the detections which are too faint

    """

    # Calculate image mean and stddev
    global_mean = np.mean(ff.avepixel)

    # Check if the image is too bright
    if global_mean > max_global_intensity:
        return np.array([]), np.array([])

    # Mask too bright regions of the image
    masked_average = maskBright(ff.avepixel, global_mean, max_abs_chunk_intensity=max_global_intensity)

    # Stretch image intensity with arcsinh
    limg = np.arcsinh(masked_average.astype(np.float32))
    limg = limg / limg.max()

    # Find local maximums
    lm = feature.peak_local_max(limg, min_distance=15, num_peaks=max_stars)

    # Skip if no local maxima found
    if not lm.shape:
        return np.array([]), np.array([])

    y1, x1 = np.hsplit(lm, 2)

    # Choose local maximums above a given intensity threshold
    v = limg[(y1,x1)]
    lim = star_threshold
    x2, y2 = x1[v > lim], y1[v > lim]

    return x2, y2


def twoD_Gaussian((x, y), amplitude, xo, yo, sigma_x, sigma_y, theta, offset):
    """ Defines a 2D Gaussian distribution. """
    xo = float(xo)
    yo = float(yo)    
    a = (np.cos(theta)**2)/(2*sigma_x**2) + (np.sin(theta)**2)/(2*sigma_y**2)
    b = -(np.sin(2*theta))/(4*sigma_x**2) + (np.sin(2*theta))/(4*sigma_y**2)
    c = (np.sin(theta)**2)/(2*sigma_x**2) + (np.cos(theta)**2)/(2*sigma_y**2)
    g = offset + amplitude*np.exp( - (a*((x-xo)**2) + 2*b*(x-xo)*(y-yo) + c*((y-yo)**2)))
    return g.ravel()


def fitPSF(ff, x2, y2):
    """ Fit 2D Gaussian distribution as the PSF on the star image. 

    @param ff: [ff bin struct] FF bin file loaded in the FF bin structure
    @param x2: [list] a list of estimated star position (X axis)
    @param xy: [list] a list of estimated star position (Y axis)
    """

    # Calculate the mean of the avepixel image
    avepixel_mean = np.mean(ff.avepixel)

    x_fitted = []
    y_fitted = []
    
    for star in zip(list(y2), list(x2)):

        y, x = star

        star_radius = 10 # px

        y_min = y - star_radius
        y_max = y + star_radius
        x_min = x - star_radius
        x_max = x + star_radius

        if y_min < 0:
            y_min = 0
        if y_max > ff.nrows:
            y_max = ff.nrows
        if x_min < 0:
            x_min = 0
        if x_max > ff.ncols:
            x_max = ff.ncols

        # Extract an image segment around each star
        star_seg = ff.avepixel[y_min:y_max, x_min:x_max]

        # Create x and y indices
        x_ind, y_ind = np.indices(star_seg.shape)

        # Fit a PSF to the star
        initial_guess = (30.0, star_radius, star_radius, 1.0, 1.0, -10.0, avepixel_mean)

        try:
            popt, pcov = opt.curve_fit(twoD_Gaussian, (x_ind, y_ind), star_seg.ravel(), p0=initial_guess, maxfev=100)
            # print popt
        except:
            # print 'Fitting failed!'
            continue

        amplitude, xo, yo, sigma_x, sigma_y, theta, offset = popt

        x_fitted.append(x_min + xo)
        y_fitted.append(y_min + yo)


        # # Plot fitted stars
        # data_fitted = twoD_Gaussian((x_ind, y_ind), *popt)

        # fig, ax = plt.subplots(1, 1)
        # ax.hold(True)
        # ax.imshow(star_seg.reshape(star_radius*2, star_radius*2), cmap=plt.cm.jet, origin='bottom',
        #     extent=(x_ind.min(), x_ind.max(), y_ind.min(), y_ind.max()))
        # ax.contour(y_ind, x_ind, data_fitted.reshape(star_radius*2, star_radius*2), 8, colors='w')

        # plt.show()
        # plt.clf()
        # plt.close()

    return x_fitted, y_fitted




if __name__ == "__main__":

    if not len(sys.argv) == 2:
        print "Usage: python -m RMS.ExtractStars /path/to/bin/files/"
        sys.exit()
    
    # Get paths to every FF bin file in a directory 
    ff_list = [ff for ff in os.listdir(sys.argv[1]) if ff[0:2]=="FF" and ff[-3:]=="bin"]

    # Check if there are any file in the directory
    if(len(ff_list) == None):
        print "No files found!"
        sys.exit()

    # Go through all files in the directory
    for ff_name in sorted(ff_list):

        print ff_name

        # Load the FF bin file
        ff = FFbin.read(sys.argv[1], ff_name)

        t1 = time.clock()

        # Run star extraction
        x2, y2 = extractStars(ff)

        print x2, y2

        # Skip if no stars were found
        if not (x2.shape and y2.shape):
            continue

        # Fit a PSF to each star
        x2, y2 = fitPSF(ff, x2, y2)

        print 'Time for finding: ', time.clock() - t1

        print x2, y2


        # Plot image
        plt.imshow(np.arcsinh(ff.avepixel), cmap='gray')

        # Plot stars
        for star in zip(list(y2), list(x2)):
            y, x = star
            c = plt.Circle((x, y), 5, fill=False, color='r')
            plt.gca().add_patch(c)

        plt.show()

        plt.clf()
        plt.close()


