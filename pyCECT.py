#! /usr/bin/env python
import getopt
import glob
import json
import os
import random
import re
import sys
import time
from datetime import datetime

import netCDF4 as nc
import numpy as np

import pyEnsLib
import pyTools
from pyTools import EqualStride

# This routine compares the results of several (default=3) new CAM tests
# or a POP test or an MPAS-A test against the accepted ensemble
# (generated by pyEnsSum or  pyEnsSumPop or PyEnsSumMPAS).

def main(argv):
    # Get command line stuff and store in a dictionary
    s = """verbose sumfile= indir= input_globs= tslice= nPC= sigMul=
         minPCFail= minRunFail= numRunFile= popens mpas pop cam
         jsonfile= mpi_enable nbin= minrange= maxrange= outfile=
         casejson= npick= pepsi_gm pop_tol= web_enabled
         base_year= pop_threshold= printStdMean fIndex= lev= eet= saveResults json_case=  saveEET="""
    optkeys = s.split()
    try:
        opts, args = getopt.getopt(argv, 'h', optkeys)
    except getopt.GetoptError:
        pyEnsLib.CECT_usage()
        sys.exit(2)

    # Set the default value for options
    opts_dict = {}
    opts_dict['input_globs'] = ''
    opts_dict['indir'] = ''
    opts_dict['tslice'] = 0
    opts_dict['nPC'] = -1
    opts_dict['sigMul'] = -2
    opts_dict['verbose'] = False
    opts_dict['minPCFail'] = 3
    opts_dict['minRunFail'] = 2
    opts_dict['numRunFile'] = 3
    opts_dict['popens'] = False
    opts_dict['mpas'] = False
    opts_dict['cam'] = True
    opts_dict['pop'] = False
    opts_dict['jsonfile'] = ''
    opts_dict['mpi_enable'] = False
    opts_dict['nbin'] = 40
    opts_dict['minrange'] = 0.0
    opts_dict['maxrange'] = 4.0
    opts_dict['outfile'] = 'testcase.result'
    opts_dict['casejson'] = ''
    opts_dict['npick'] = 10
    opts_dict['pepsi_gm'] = False
    opts_dict['test_failure'] = True
    opts_dict['pop_tol'] = 3.0
    opts_dict['pop_threshold'] = 0.90
    opts_dict['printStdMean'] = False
    opts_dict['lev'] = 0
    opts_dict['eet'] = 0
    opts_dict['json_case'] = ''
    opts_dict['sumfile'] = ''
    opts_dict['web_enabled'] = False
    opts_dict['saveResults'] = False
    opts_dict['base_year'] = 1
    opts_dict['saveEET'] = ''

    # Call utility library getopt_parseconfig to parse the option keys
    # and save to the dictionary
    caller = 'CECT'
    opts_dict = pyEnsLib.getopt_parseconfig(opts, optkeys, caller, opts_dict)

    # ens type
    # cam = opts_dict['cam']
    popens = opts_dict['popens']
    pop = opts_dict['pop']
    mpas = opts_dict['mpas']

    #print(f'!test mpas:{mpas}')

    if pop or popens:
        ens = 'pop'
    elif mpas:
        ens = 'mpas'
    else:
        ens = 'cam'

    #for POP-ECT only take one file
    if ens == 'pop':
        opts_dict['numRunFile'] = 1

    # some more specific defaults (if not specified)   
    if ens =='mpas':
        if opts_dict['nPC'] < 0:
            opts_dict['nPC'] = 26
        if opts_dict['sigMul'] < 0:
            opts_dict['sigMul'] = 2
    elif ens == 'cam':
        if opts_dict['nPC'] < 0:
            opts_dict['nPC'] = 128
        if opts_dict['sigMul']  < 0:
            opts_dict['sigMul'] = 2.23

    print('Parameter values:')    
    print(opts_dict)    

        
    # Create a mpi simplecomm object
    if opts_dict['mpi_enable']:
        me = pyTools.create_comm()
    else:
        me = pyTools.create_comm(not opts_dict['mpi_enable'])

    # Print out timestamp, input ensemble file and new run directory
    dt = datetime.now()
    verbose = opts_dict['verbose']
    if me.get_rank() == 0:
        print(' ')
        print('--------pyCECT--------')
        print(' ')
        print(dt.strftime('%A, %d. %B %Y %I:%M%p'))
        print(' ')
        print('Ensemble type = ', ens)
        print(' ')
        if not opts_dict['web_enabled']:
            print('Ensemble summary file = ' + opts_dict['sumfile'])
        print(' ')
        print('Testcase file directory = ' + opts_dict['indir'])
        print(' ')
        print(' ')

    # make sure these are valid
    if opts_dict['web_enabled'] is False and os.path.isfile(opts_dict['sumfile']) is False:
        print('ERROR: Summary file name is not valid.')
        sys.exit()
    if os.path.exists(opts_dict['indir']) is False:
        print('ERROR: --indir path is not valid.')
        sys.exit()

    # Ensure sensible EET value
    if opts_dict['eet'] and opts_dict['numRunFile'] > opts_dict['eet']:
        pyEnsLib.CECT_usage()
        sys.exit(2)

    ifiles = []
    in_files = []
    # Random pick pop files from not_pick_files list
    if opts_dict['casejson']:
        with open(opts_dict['casejson']) as fin:
            result = json.load(fin)
            in_files_first = result['not_pick_files']
            in_files = random.sample(in_files_first, opts_dict['npick'])
            print('Testcase files:')
            print('\n'.join(in_files))

    elif opts_dict['json_case']:
        json_file = opts_dict['json_case']
        if os.path.exists(json_file):
            fd = open(json_file)
            metainfo = json.load(fd)
            if 'CaseName' in metainfo:
                casename = metainfo['CaseName']
                if os.path.exists(opts_dict['indir']):
                    for name in casename:
                        wildname = '*.' + name + '.*'
                        full_glob_str = os.path.join(opts_dict['indir'], wildname)
                        glob_file = glob.glob(full_glob_str)
                        in_files.extend(glob_file)
        else:
            print('ERROR: ' + opts_dict['json_case'] + ' does not exist.')
            sys.exit()
        print('in_files=', in_files)
    else:
        wildname = '*' + str(opts_dict['input_globs']) + '*.nc'
        # Open all input files
        if os.path.exists(opts_dict['indir']):
            full_glob_str = os.path.join(opts_dict['indir'], wildname)
            glob_files = glob.glob(full_glob_str)
            in_files.extend(glob_files)
            num_file = len(in_files)
            if num_file == 0:
                print(
                    'ERROR: no matching files for wildcard='
                    + wildname
                    + ' found in specified --indir'
                )
                sys.exit()
            else:
                print('Found ' + str(num_file) + ' matching files in specified --indir')
            if opts_dict['numRunFile'] > num_file:
                print(
                    'ERROR: more files needed ('
                    + str(opts_dict['numRunFile'])
                    + ') than available in the indir ('
                    + str(num_file)
                    + ').'
                )
                sys.exit()

    in_files.sort()
    # print in_files

    if ens == 'pop':
        # Partition the input file list
        in_files_list = me.partition(in_files, func=EqualStride(), involved=True)

    else:  # cam or mpas
        # Random pick
        in_files_list = pyEnsLib.Random_pickup(in_files, opts_dict)

    for frun_file in in_files_list:
        if frun_file.find(opts_dict['indir']) != -1:
            frun_temp = frun_file
        else:
            frun_temp = opts_dict['indir'] + '/' + frun_file
        if os.path.isfile(frun_temp):
            ifiles.append(frun_temp)
        else:
            print('ERROR: COULD NOT LOCATE FILE ' + frun_temp)
            sys.exit()

    if opts_dict['web_enabled']:
        if len(opts_dict['sumfile']) == 0:
            opts_dict['sumfile'] = '/glade/p/cesmdata/cseg/inputdata/validation/'
        # need to open ifiles

        opts_dict['sumfile'], machineid, compiler = pyEnsLib.search_sumfile(opts_dict, ifiles)
        if len(machineid) != 0 and len(compiler) != 0:
            print(' ')
            print('Validation file    : machineid = ' + machineid + ', compiler = ' + compiler)
            print('Found summary file : ' + opts_dict['sumfile'])
            print(' ')
        else:
            print('Warning: machine and compiler are unknown')

    if ens == 'pop':
        # Read in the included var list
        if not os.path.exists(opts_dict['jsonfile']):
            print('ERROR: POP-ECT requires the specification of a valid json file via --jsonfile.')
            sys.exit()
        Var2d, Var3d = pyEnsLib.read_jsonlist(opts_dict['jsonfile'], 'ESP')
        print(' ')
        print('Z-score tolerance = ' + '{:3.2f}'.format(opts_dict['pop_tol']))
        print('ZPR = ' + '{:.2%}'.format(opts_dict['pop_threshold']))
        zmall, n_timeslice = pyEnsLib.pop_compare_raw_score(
            opts_dict, ifiles, me.get_rank(), Var3d, Var2d
        )

        np.set_printoptions(threshold=sys.maxsize)

        if opts_dict['mpi_enable']:
            zmall = pyEnsLib.gather_npArray_pop(
                zmall, me, (me.get_size(), len(Var3d) + len(Var2d), len(ifiles), opts_dict['nbin'])
            )
            if me.get_rank() == 0:
                fout = open(opts_dict['outfile'], 'w')
                for i in range(me.get_size()):
                    for j in zmall[i]:
                        np.savetxt(fout, j, fmt='%-7.2e')

    # mpas and cam
    else:
        if ens == 'mpas':
            # Read all variables from the ensemble summary file
            (
                ens_var_name,
                num_varCell,
                num_varEdge,
                num_varVertex,
                mu_gm,
                sigma_gm,
                loadings_gm,
                sigma_scores_gm,
                std_gm,
                std_gm_array,
                str_size,
                ens_gm,
            ) = pyEnsLib.mpas_read_ensemble_summary(opts_dict['sumfile'])

            # total vars
            total_vars = len(ens_var_name)

            # Add global mean to the dictionary "variables"
            variables = {}
            for k, v in ens_gm.items():
                pyEnsLib.addvariables(variables, k, 'gmRange', v)

            varCell_name = ens_var_name[0:num_varCell]
            varEdge_name = ens_var_name[num_varCell : num_varCell + num_varEdge]
            varVertex_name = ens_var_name[num_varCell + num_varEdge :]

            # Compare the new run and the ensemble summary file
            results = {}
            countgm = np.zeros(len(ifiles), dtype=np.int32)

            gmCell, gmEdge, gmVertex = pyEnsLib.generate_global_mean_for_summary_MPAS(
                ifiles, varCell_name, varEdge_name, varVertex_name, opts_dict
            )

            means = np.concatenate((gmCell, gmEdge, gmVertex), axis=0)
            # end mpas

        else:  # cam
            # Read all variables from the ensemble summary file
            (
                ens_var_name,
                ens_avg,
                ens_stddev,
                ens_rmsz,
                ens_gm,
                num_3d,
                mu_gm,
                sigma_gm,
                loadings_gm,
                sigma_scores_gm,
                is_SE_sum,
                std_gm,
                std_gm_array,
                str_size,
            ) = pyEnsLib.read_ensemble_summary(opts_dict['sumfile'])

            # total vars
            total_vars = len(ens_var_name)

            # Add global mean to the dictionary "variables"
            variables = {}

            for k, v in ens_gm.items():
                pyEnsLib.addvariables(variables, k, 'gmRange', v)

            # Get 3d variable name list and 2d variable name list separately
            var_name3d = []
            var_name2d = []
            for vcount, v in enumerate(ens_var_name):
                if vcount < num_3d:
                    var_name3d.append(v)
                else:
                    var_name2d.append(v)

            ###
            npts3d, npts2d, is_SE = pyEnsLib.get_ncol_nlev(ifiles[0])

            if is_SE ^ is_SE_sum:
                print(
                    'Warning: please note the ensemble summary file is different from the testing files: they use different grids'
                )

            # Compare the new run and the ensemble summary file
            results = {}
            countgm = np.zeros(len(ifiles), dtype=np.int32)

            # Calculate the new run global mean
            mean3d, mean2d = pyEnsLib.generate_global_mean_for_summary(
                ifiles, var_name3d, var_name2d, is_SE, opts_dict
            )
            means = np.concatenate((mean3d, mean2d), axis=0)
            # end cam

        # NOW this the same for MPAS and CAM

        # check nPC

        if opts_dict['nPC'] > total_vars:
            new_pc = int(total_vars * 0.8)
            print(
                'Warning: please note the number of PCs specified (option --nPC) is set to ',
                opts_dict['nPC'],
                ', which exceeds the number of PC scores in the summary file (',
                total_vars,
                '). Instead using --nPC ',
                new_pc,
                '.',
            )

            opts_dict['nPC'] = new_pc

        # extra info
        # Add the new run global mean to the dictionary "results"
        for i in range(means.shape[1]):
            for j in range(means.shape[0]):
                pyEnsLib.addresults(results, 'means', means[j][i], ens_var_name[j], 'f' + str(i))
        # Evaluate the new run global mean if it is in the range of the ensemble summary global mea?n range
        for fcount, fid in enumerate(ifiles):
            countgm[fcount] = pyEnsLib.evaluatestatus(
                'means', 'gmRange', variables, 'gm', results, 'f' + str(fcount)
            )
        # end extra

        # Calculate the PCA scores of the new run
        new_scores, sum_std_mean, comp_std_gm = pyEnsLib.standardized(
            means, mu_gm, sigma_gm, loadings_gm, ens_var_name, opts_dict, me
        )
        run_index, decision = pyEnsLib.comparePCAscores(
            ifiles, new_scores, sigma_scores_gm, opts_dict, me
        )

        # which vars are most outside the standardize mean (should be zero)
        sort_index = np.argsort(sum_std_mean)[::-1]
        sorted_sum = sum_std_mean[sort_index]
        sorted_name = np.array(ens_var_name)[sort_index]
        sorted_comp_std_gm = comp_std_gm[sort_index]

        if opts_dict['printStdMean'] or decision == 'FAILED':
            print(' ')
            print('***************************************************************************** ')
            print('Test run variable standardized mean information')
            print('***************************************************************************** ')
            print(' ')

            all_outside99 = []
            two_outside99 = []
            one_outside99 = []

            # std_gm is a dictionary
            tsize = comp_std_gm.shape[1]
            b = list(ens_var_name)
            for f, avar in enumerate(b):
                if np.ma.is_masked(std_gm[avar]):
                    tempa = std_gm[avar]
                else:
                    tempa = np.array(std_gm[avar])
                dist_995 = np.percentile(tempa, 99.5)
                dist_005 = np.percentile(tempa, 0.5)
                # print(avar, " = ", dist_005, dist_995)
                count = 0
                for i in range(tsize):
                    if comp_std_gm[f, i] > dist_995 or comp_std_gm[f, i] < dist_005:
                        count = count + 1
                if count == 1:
                    one_outside99.append(avar)
                elif count == 2:
                    two_outside99.append(avar)
                elif count == tsize:
                    all_outside99.append(avar)

            if len(all_outside99) > 0:
                print(
                    '*** ',
                    len(all_outside99),
                    ' variable(s) have all test run global means outside of the 99th percentile.',
                )
                print(all_outside99)
            if len(two_outside99) > 0:
                print(
                    '*** ',
                    len(two_outside99),
                    ' variable(s) have 2 test run global means outside of the 99th percentile.',
                )
                print(two_outside99)
            if len(one_outside99) > 0:
                print(
                    '*** ',
                    len(one_outside99),
                    ' variable(s) have 1 test run global means outside of the 99th percentile.',
                )
                print(one_outside99)

            if len(all_outside99) + len(two_outside99) + len(one_outside99) == 0:
                print('*** No variables have test run global means outside of the 99th percentile.')

            # count = len(all_outside99) + len(two_outside99) + len(one_outside99)
            # count = max(10, count)
            count = 20
            count = min(count, means.shape[0])

            print('')
            print('***************************************************************************** ')
            print(
                'Top 20 test run variables in decreasing order of (abs) standardized mean sum (note: ensemble is standardized such that mean = 0 and std_dev = 1)'
            )
            for i in range(count):
                print(
                    sorted_name[i],
                    ': ',
                    'sum =',
                    sorted_sum[i],
                    '  (indiv. test run values = ',
                    sorted_comp_std_gm[i, :],
                    ')',
                )
            print('***************************************************************************** ')

        ##
        # Print file with info about new test runs....to a netcdf file
        ##
        if opts_dict['saveResults']:
            num_vars = comp_std_gm.shape[0]
            tsize = comp_std_gm.shape[1]
            esize = std_gm_array.shape[1]
            this_savefile = 'savefile.nc'
            if verbose:
                print('VERBOSE: Creating ', this_savefile, '  ...')

            if os.path.exists(this_savefile):
                os.unlink(this_savefile)
            nc_savefile = nc.Dataset(this_savefile, 'w', format='NETCDF4_CLASSIC')
            nc_savefile.createDimension('ens_size', esize)
            nc_savefile.createDimension('test_size', tsize)
            nc_savefile.createDimension('nvars', num_vars)
            nc_savefile.createDimension('str_size', str_size)

            # Set global attributes
            now = time.strftime('%c')
            nc_savefile.creation_date = now
            nc_savefile.title = 'PyCECT compare results file'
            nc_savefile.summaryfile = opts_dict['sumfile']
            # nc_savefile.testfiles = in_files

            # variables
            v_vars = nc_savefile.createVariable('vars', 'S1', ('nvars', 'str_size'))
            v_std_gm = nc_savefile.createVariable('std_gm', 'f8', ('nvars', 'test_size'))
            v_scores = nc_savefile.createVariable('scores', 'f8', ('nvars', 'test_size'))
            v_ens_sigma_scores = nc_savefile.createVariable('ens_sigma_scores', 'f8', ('nvars',))
            v_ens_std_gm = nc_savefile.createVariable('ens_std_gm', 'f8', ('nvars', 'ens_size'))

            # v_ens_loadings = nc_savefile.createVariable('ens_loadings', 'f8', ('nvars', 'nvars'))
            v_gm = nc_savefile.createVariable('gm', 'f8', ('nvars', 'test_size'))

            # hard-coded size
            ssize = 'S' + str(str_size)
            str_out = nc.stringtochar(np.array(ens_var_name, ssize))

            v_vars[:] = str_out
            v_std_gm[:, :] = comp_std_gm[:, :]
            v_scores[:, :] = new_scores[:, :]
            v_ens_sigma_scores[:] = sigma_scores_gm[:]
            v_ens_std_gm[:, :] = std_gm_array[:, :]

            # v_ens_loadings[:,:] = loadings_gm[:,:]
            v_gm[:, :] = means[:, :]

            nc_savefile.close()

        # end of CAM and MPAS

    if me.get_rank() == 0:
        print(' ')
        print('Testing complete.')
        print(' ')


if __name__ == '__main__':
    main(sys.argv[1:])
