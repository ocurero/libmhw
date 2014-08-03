libmhw
======

A python module to fetch MHW DVB propietary data

Usage
=====

    from libmhw import MHW
    data = MHW()
    channels, programs = data.scan_stream("/dev/dvb/adapter0/demux0")
    for program in program:
        print program
