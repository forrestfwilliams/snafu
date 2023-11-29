import subprocess

import numpy as np
from osgeo import gdal


base_template = '''
    ######################
    # Base Configuration #
    ######################

    # Input file name
    INFILE  {infile}
    INFILEFORMAT    {informat}

    # Input file line length
    LINELENGTH  {width}
    NLOOKSRANGE {looks_range}
    NLOOKSAZ    {looks_az}

    # Output file
    OUTFILE {outfile}
    OUTFILEFORMAT   {outformat}

    # Correlation file
    CORRFILE    {corfile}
    CORRFILEFORMAT  FLOAT_DATA

    # Unwrapping Controls
    STATCOSTMODE    DEFO
    DEFOMAX_CYCLE   4.0
    INITMETHOD  MCF
    MAXNCOMPS   32

    '''

tile_template = '''
    ################
    # Tile control #
    ################

    # Parameters in this section describe how the input files will be
    # tiled.  This is mainly used for tiling, in which different
    # patches of the interferogram are unwrapped separately.

    # Number of rows and columns of tiles into which the data files are
    # to be broken up.
    NTILEROW    {ntilerow}
    NTILECOL    {ntilecol}

    # Overlap, in pixels, between neighboring tiles.
    # Using the same overlap for rows and cols here, but they can be different in general
    ROWOVRLP    {overlap}
    COLOVRLP    {overlap}

    # Maximum number of child processes to start for parallel tile
    # unwrapping.
    NPROC   {nproc}

    '''

mask_template = '''
    ###########
    # Masking #
    ###########

    # Input file of signed binary byte (signed char) values.  Values in
    # the file should be either 0 or 1, with 0 denoting interferogram
    # pixels that should be masked out and 1 denoting valid pixels.  The
    # array should have the same dimensions as the input wrapped phase
    # array.
    BYTEMASKFILE    {mask}

    '''

unwrap_template = """
    UNWRAPPED_IN    TRUE
    UNWRAPPEDINFILEFORMAT   FLOAT_DATA

    """


def write_snaphu_config(
    in_ifg,
    in_cor,
    looks_az,
    looks_range,
    shape,
    out_conf,
    out_file,
    tile_shape=None,
    tile_overlap=600,
    in_mask=None,
    unwrapped=False,
):
    '''Writes a configuration file that is readable by SNAPHU'''
    # in_format = 'FLOAT_DATA' if unwrapped else 'COMPLEX_DATA'
    in_format = 'FLOAT_DATA'

    options = dict(
        infile=in_ifg,
        informat=in_format,
        corfile=in_cor,
        looks_az=looks_az,
        looks_range=looks_range,
        width=shape[1],
        outfile=out_file,
        outformat='FLOAT_DATA',
    )

    template = base_template
    if tile_shape:
        ntilerow, ntilecol = tile_shape
        nproc = ntilerow * ntilecol
        template += tile_template
        options['ntilerow'] = ntilerow
        options['ntilecol'] = ntilecol
        options['overlap'] = tile_overlap
        options['nproc'] = nproc

    if in_mask:
        template += mask_template
        options['mask'] = in_mask

    if unwrapped:
        template += unwrap_template

    template = template.format(**options)

    with open(out_conf, "w") as f:
        f.write(template)

    return out_conf, out_file


def gdal_to_binary(inpath, outpath, dtype):
    if dtype == gdal.GDT_Float32:
        py_dtype = np.float32
    elif dtype == gdal.GDT_Byte:
        py_dtype = np.byte
    elif dtype == gdal.GDT_CFloat32:
        py_dtype = np.float32
    else:
        raise NotImplementedError

    ds = gdal.Open(inpath)
    arr = ds.GetRasterBand(1).ReadAsArray(buf_type=dtype)
    ds = None
    if dtype == gdal.GDT_CFloat32:
        arr = np.angle(arr)

    arr = arr.astype(py_dtype)
    arr.tofile(outpath)


def binary_to_gdal(inpath, templatepath, maskpath, outpath):
    ds = gdal.Open(templatepath)
    nodata_value = ds.GetRasterBand(1).GetNoDataValue()
    dtype = ds.GetRasterBand(1).DataType
    shape = (ds.RasterYSize, ds.RasterXSize)

    if dtype == gdal.GDT_Float32:
        py_dtype = np.float32
    elif dtype == gdal.GDT_Byte:
        py_dtype = np.byte
    else:
        raise NotImplementedError

    mask_ds = gdal.Open(maskpath)
    mask = mask_ds.GetRasterBand(1).ReadAsArray()
    mask_ds = None

    arr = np.fromfile(inpath, dtype=py_dtype).reshape(shape)
    arr[mask == 0] = nodata_value

    driver = gdal.GetDriverByName('GTiff')
    out_ds = driver.Create(outpath, shape[1], shape[0], 1, dtype)
    out_ds.SetGeoTransform(ds.GetGeoTransform())
    out_ds.SetProjection(ds.GetProjection())
    out_ds.GetRasterBand(1).WriteArray(arr)
    out_ds.GetRasterBand(1).SetNoDataValue(nodata_value)
    ds = None
    out_ds = None


def main():
    files = [
        ('bursts_unwrapped', gdal.GDT_Float32),
        ('bursts_unwrapped_corrected', gdal.GDT_Float32),
        ('bursts_wrapped', gdal.GDT_Float32),
        ('bursts_correlation', gdal.GDT_Float32),
        ('bursts_mask', gdal.GDT_Byte),
    ]
    for name, dtype in files:
        gdal_to_binary(f'{name}.tif', f'{name}.bin', dtype)

    ds = gdal.Open('bursts_wrapped.tif')
    n_lines = ds.RasterYSize
    n_pixels = ds.RasterXSize
    ds = None

    write_snaphu_config(
        in_ifg='bursts_unwrapped.bin',
        # in_ifg='bursts_wrapped.bin',
        in_cor='bursts_correlation.bin',
        shape=(n_lines, n_pixels),
        looks_az = 4,
        looks_range = 20,
        out_conf='snaphu.conf',
        out_file='bursts_reunwrapped.bin',
        # tile_shape=(3, 3),
        # tile_overlap=600,
        in_mask='bursts_mask.bin',
        unwrapped=True,
    )

    print('Outputting looked unwrapped phase to', 'bursts_reunwrapped.bin')
    cmd = 'snaphu -f snaphu.conf |& tee -i snaphu.log'
    print(cmd)
    subprocess.call(cmd, shell=True)
    binary_to_gdal('bursts_reunwrapped.bin', 'bursts_wrapped.tif', 'bursts_mask.tif', 'bursts_reunwrapped.tif')


if __name__ == '__main__':
    main()
