#!/usr/bin/python
# Created by Christopher Nguyen
# 5/17/2010

#import modules
import time
import sys, os, traceback, optparse
import numpy as np
import scipy as sp

#HBCAN utilities
#sys.path.append('/home/cnguyen/scripts/HBCAN/utils')
#from io import get_coord_4D_to_3D

class tensor(object):
    """
    Tensor object that when initialized calculates single self diffusion tensor[1]_ in 
    each voxel using selected fitting algorithm (DEFAULT: weighted least squares[1]_)

    Requires a given gradient table, b value for each diffusion-weighted gradient vector,
    and image data given all as numpy ndarrays.

    Key Methods
    -----------
    evals : ndarray (X,Y,Z,EV1,EV2,EV3)Z
        Returns cached eigenvalues of self diffusion tensor [1]_ for given index.
    evecs : ndarray (X,Y,Z,EV1x,EV1y,EV1z,EV2x,EV2y,EV2z,EV3x,EV3y,EV3z)
        Returns cached associated eigenvector of self diffusion tensor [1]_ for given 
        index.
    FA : ndarray
        Calculates fractional anisotropy [2]_ for given index.
    ADC : ndarray
        Calculates apparent diffusion coefficient or mean diffusitivity [2]_ for given
        index.

    References
    ----------
    ..    [1] Basser, P.J., Mattiello, J., LeBihan, D., 1994. Estimation of the effective 
        self-diffusion tensor from the NMR spin echo. J Magn Reson B 103, 247-254.
    ..    [2] Basser, P., Pierpaoli, C., 1996. Microstructural and physiological features 
        of tissues elucidated by quantitative-diffusion-tensor MRI. Journal of Magnetic 
        Resonance 111, 209-219.
    
    """
    def _getshape(self):
        pass

    def _getndim(self):
        pass

    def __getitem__(self,index):
        pass
    
    def __init__(self, data, grad_table, b_values, mask=None,thresh=5,verbose=None):
        fit_data, scalars = WLS_fit(data,grad_table,b_values,scalars=1,verbose=verbose,mask=mask,thresh=thresh)
        self.evals = scalars[:,:,:,0:3]
        self.evecs = scalars[:,:,:,3:12]
        self.prime_evec = scalars[:,:,:,3:6]
        self.adc = self.calc_adc()
        self.fa = self.calc_fa()
    
    def calc_D(self):
        D = np.dot(np.dot(Q,delta),np.linalg.pinv(Q))
        return D
        pass

    def calc_adc(self):
        #adc = (ev1+ev2+ev3)/3
        return (self.evals[:,:,:,0] + self.evals[:,:,:,1] + self.evals[:,:,:,2]) / 3

    def calc_fa(self):
        adc = self.calc_adc()
        ev1 = self.evals[:,:,:,0]
        ev2 = self.evals[:,:,:,1]
        ev3 = self.evals[:,:,:,2]
        ss_ev = ev1**2+ev2**2+ev3**2
        
        fa = np.zeros(ev1.shape,dtype='float32') #'int16')
        fa = np.sqrt( 1.5 * ( (ev1-adc)**2+(ev2-adc)**2+(ev3-adc)**2 ) / ss_ev )
        fa[ss_ev == 0] = 0
        return fa 


def WLS_fit (data,gtab,bval,scalars=None,mask=None,thresh=None,verbose=None,out_root='noroot'):    
    """
    Computes weighted least squares (WLS) fit to calculate self-diffusion tensor. 
    (Basser et al., 1994a)

    Parameters
    ----------
    data : ndarray (X,Y,Z,g)
        The image data as a numpy ndarray.
    gtab : ndarray (3,g)
        Diffusion gradient table found in DICOM header as a numpy ndarray.
    bval : ndarray (g,1)
        Diffusion weighting factor b for each vector in gtab.
    scalars : integer (0,1)
        Flag that returns integers.


    """
    start_time = time.time()
    ####main part of code
    dims = data.shape
    
    if mask != None and dims[0:3] != mask.shape :
        raise ValueError('Data image and mask MUST have same 3D volume shape!')

    ###Create log of signal and reshape it to be x:y:z by grad
    fit_dim = (dims[0]*dims[1]*dims[2],dims[3])
    data = data.reshape(fit_dim) #direct reshape for some reason does not work
    #log_s = np.zeros(fit_dim,dtype='float32')
    #log_s_ols = np.zeros(fit_dim,dtype='int16')
    
    # Y matrix from Chris' paper
    # enforcing positive values to allow for natural log
    data[data <= 0] = 1
    # need to set this seperately to enforce int16 precision
    # set precision to 3 significant figures...to save memory
    # instead of later calculating it with log_s_ols
    log_s = np.int16(np.log(data) * 1000)
    del data #freeing up memory

    ###Construct design matrix
    #For DTI this is the so called B matrix
    # X matrix from Chris' paper
    B = design_matrix(gtab,bval) # [g by 7]
	
    ###Weighted Least Squares (WLS) to solve "linear" regression
    # Y hat OLS from Chris' paper
    #  ( [g by 7] [7 by g ] [ g by x*y*z ] ).T = [x*y*z by g]
    log_s_ols = np.int16(np.dot(np.dot(B, np.linalg.pinv(B)), log_s.T)).T
    #del log_s #freeing up memory

    #Setting these arrays later to allow the previous step to have all memory
    fit_data = np.zeros(fit_dim,dtype='int16') #original data is int16
    
    if scalars == 1:
        scalar_maps = np.zeros((fit_dim[0],12),dtype='float32')#'int16')

    time_diff = list((0,0))
    time_iter = time.time()
    # This step is because we cannot vectorize diagonal vector and tensor fit
    for i in range(np.size(log_s_ols,axis=0)):
        #Check every 1 slices
        if verbose == 1 and i % (dims[0]*dims[1]*1) == 0:
            slice = i/dims[0]/dims[1]+1.
            time_diff.append(time.time()-time_iter)
            min = np.mean(time_diff[2:len(time_diff)])/60.0/5*(dims[2]-slice)
            sec = np.round((min - np.fix(min)) * 60.0/5)
            min = np.fix(min)
            percent = 100.*slice/dims[2]
            print str(np.round(percent)) + '% ... time left ' + str(min) + ' MIN ' + str(sec) + ' SEC'
            time_iter=time.time()
 
        if mask != None and mask.flat[i] == 0:
            continue

        if thresh != None and np.exp(log_s[i,0]/1000.) < thresh:
            continue

        #if not finite move on
        #if not(np.unique(np.isfinite(log_s[:,i]))[0]) :
        #    continue

        #Split up weighting vector into little w to perform pinv
        w = np.exp(log_s_ols[i,:]/1000.)[:,np.newaxis]
    
        #pointwise broadcasting to avoid diagonal matrix multiply!
        D = np.dot(np.linalg.pinv(B*w), w.ravel()*log_s[i,:]/1000.) #np.log(data[:,i]))
        fit_data[i,:] = np.int16(np.exp(np.dot(B,D))) 
        
        ###Calculate scalar maps
        if scalars == 1:
            scalar_maps[i,:] = calc_dti_scalars(D[0:6],scale=1)

    #clear variables not needed to save memory
    del log_s_ols

    #Fit the data with estimate of D
    #fit_data = np.round(np.dot(B,D)) 
    
    # Reshape the output images
    #fit_data.shape = dims
    #data.shape = dims
    fit_data = fit_data.reshape(dims)
    #data = data.reshape(dims)

    #If requesting to save scalars ...
    if scalars == 1:
        #Reshape the scalar map array
        scalar_maps = scalar_maps.reshape((dims[0],dims[1],dims[2],12))
        #save_scalar_maps(scalar_maps)
   
    #Report how long it took to make the fit  
    if verbose == 1:
        min = (time.time() - start_time) / 60.0
        sec = (min - np.fix(min)) * 60.0
        print 'TOTAL TIME: ' + str(np.fix(min)) + ' MIN ' + str(np.round(sec)) + ' SEC'

    return(fit_data, scalar_maps)


def calc_dti_scalars(D,scale=1):
    tensor = np.zeros((3,3))
    tensor[0,0] = D[0]  #Dxx
    tensor[1,1] = D[1]  #Dyy
    tensor[2,2] = D[2]  #Dzz
    tensor[1,0] = D[3]  #Dxy
    tensor[2,0] = D[4]  #Dxz
    tensor[2,1] = D[5]  #Dyz
    tensor[0,1] = tensor[1,0] #Dyx
    tensor[0,2] = tensor[2,0] #Dzx
    tensor[1,2] = tensor[2,1] #Dzy

    #outputs multiplicity as well so need to unique
    eigenvals, eigenvecs = np.linalg.eig(tensor)

    if np.size(eigenvals) != 3:
        raise ValueError('not 3 eigenvalues : ' + str(eigenvals))

    #need to sort the eigenvalues and associated eigenvectors
    eigenvecs = eigenvecs[:,eigenvals.argsort()[::-1]]
    eigenvals.sort() #very fast
    eigenvals = eigenvals[::-1]

    #Forcing negative eigenvalues to 0
    eigenvals[eigenvals <0] = 0
    # b ~ 10^3 s/mm^2 and D ~ 10^-4 mm^2/s
    # eigenvecs: each vector is columnar
	
    dti_parameters = np.concatenate((eigenvals,eigenvecs.T.flat[:]))*scale
    #dti_parameters.dtype = 'float32' 
    return(dti_parameters)

def design_matrix(gtab,bval,dtype='float32'):
    #from CTN legacy IDL we start with [7 by g] ... sorry :(
    B = np.zeros((7,np.size(bval)),dtype=dtype)
    G = gtab
    
    if np.size(gtab,axis=1) < np.size(bval) :
        print 'Gradient table size is not consistent with bval vector... could be b/c of b0 images'
        print 'Will try to set nonzero bval index with gradient table to construct B matrix'
        
        G = np.zeros((3,np.size(bval)))
        G[:,np.where(bval > 0)]=gtab
    
    B[0,:] = G[0,:]*G[0,:]*1.*bval   #Bxx
    B[1,:] = G[1,:]*G[1,:]*1.*bval   #Byy
    B[2,:] = G[2,:]*G[2,:]*1.*bval   #Bzz
    B[3,:] = G[0,:]*G[1,:]*2.*bval   #Bxy
    B[4,:] = G[0,:]*G[2,:]*2.*bval   #Bxz
    B[5,:] = G[1,:]*G[2,:]*2.*bval   #Byz
    B[6,:] = np.ones(np.size(bval),dtype=dtype)
    
    #Need to return [g by 7]
    return -B.T


def save_scalar_maps(scalar_maps, img=None, coordmap=None):
    #for io of writing and reading nifti images
    from nipy import load_image, save_image
    from nipy.core.api import fromarray #data --> image
    
    #For writing out with save_image with appropriate affine matrix
    if img != None:
        coordmap = get_coord_4D_to_3D(img.affine)
        header = img.header.copy()

    ###Save scalar maps if requested
    print ''
    print 'Saving t2di map ... '+out_root+'_t2di.nii.gz'
        
    #fyi the dtype flag for save image does not appear to work right now...
    t2di_img = fromarray(data[:,:,:,0],'ijk','xyz',coordmap=coordmap)
    if img != []: 
        t2di_img.header = header
    save_image(t2di_img,out_root+'_t2di.nii.gz',dtype=np.int16)

        
    scalar_fnames = ('ev1','ev2','ev3','adc','fa','ev1p','ev1f','ev1s')
    for i in range(np.size(scalar_maps,axis=3)):
        #need to send in 4 x 4 affine matrix for 3D image not 5 x 5 from original 4D image
        print 'Saving '+ scalar_fnames[i] + ' map ... '+out_root+'_'+scalar_fnames[i]+'.nii.gz'
        scalar_img = fromarray(np.int16(scalar_maps[:,:,:,i]),'ijk' ,'xyz',coordmap=coordmap)
        if img != []:
            scalar_img.header = header
        save_image(scalar_img,out_root+'_'+scalar_fnames[i]+'.nii.gz',dtype=np.int16)

    print ''
    print 'Saving D = [Dxx,Dyy,Dzz,Dxy,Dxz,Dyz] map ... '+out_root+'_self_diffusion.nii.gz'
    #Saving 4D matrix holding diffusion coefficients
    if img != [] :
        coordmap = img.coordmap
        header = img.header.copy()
    tensor_img = fromarray(tensor_data,'ijkl','xyzt',coordmap=coordmap)
    tensor_img.header = header
    save_image(tensor_img,out_root+'_self_diffusion.nii.gz',dtype=np.int16)

    print

    return