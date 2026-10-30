# Time Tag Internet recording

The Time Tag window has independent **QSFP** and **Internet** checkboxes.
Internet uses the Windows service in `QCS_HH_TRX.py`; it does not import the
HydraHarp SDK or open a HydraHarp on Linux.

1. Open **Time Tag** in the Linux controller and enable **Internet**. Defaults
   are bind `0.0.0.0`, control TCP port `50051`, and data TCP port `50050`.
   Stop the standalone Linux coordinator first if it is using these ports.
2. Use the updated `QCS_HH_TRX.py` on Windows (it adds the per-recording `STOP`
   command). From the repository root run:

   ```powershell
   python Modular_Python_Controller/QCS_HH_TRX.py service --host <LINUX_IP> --source hh
   ```

   Use `--source simulate` for a test without the device. Windows must be able
   to connect to both Linux ports.
3. Wait for **Internet ready; Windows service connected**. Choose the usual
   Time Tagger X `.ttbin` file and click **Start Writing**. Time Tagger X must
   be available, as in the existing Time Tag workflow.
4. Internet data is stored separately as `<stem>.internet.bin`, with a JSON
   manifest beside it. The Windows service also keeps its local raw backup
   in `hh_spool`. Payload blocks default to 1 KiB.
5. Click **Stop Writing** to stop both recordings. The controller waits for
   the remote data to drain and the final SHA-256 check. Closing Time Tag
   during recording also waits before releasing the listener. The Windows
   device remains open for another recording.

The Internet row reports validated payload bytes written to the receiver
and current payload speed in decimal MB/s, sampled every 250 ms. After the
transfer finishes it displays the average speed, including acquisition idle
time. Failed transfers retain `.part` data and an incomplete JSON manifest;
they are not published as completed `.bin` files. Existing outputs are never
overwritten.

**Auto stop after time** supplies the remote duration (0.001 to 3600 seconds).
The Linux controller also schedules a dedicated finish callback for that
duration. For example, with a 10-second limit the Arduino gate is switched
off at 9 seconds, and at 10 seconds the local writer stops and Windows is
asked to stop. Final Internet data may take longer to arrive and verify;
the recording-time display stays frozen at the stop request while this
finishes. Manual stop cancels the old finish timer before the next recording.
Without a time limit, the remote service has a 3600-second maximum; Stop Writing
can end it earlier. **Auto stop at size** continues to use the local Time
Tagger X file size. The Internet receiver has a separate 16 GiB ceiling.

These are software-started recordings, without a guaranteed synchronized
hardware start. Matching hashes establish file-transfer integrity; automatic
HydraHarp buffer-overrun detection remains unavailable.

## Checks

Offline checks (no sockets, GUI, SDK, or hardware):

```bash
python3 -m unittest discover -s Modular_Python_Controller/tests -p test_internet_timetag.py -k Offline
```

Loopback checks, including repeated recordings and an operator stop, on a host
that permits local TCP sockets:

```bash
python3 -m unittest discover -s Modular_Python_Controller/tests -p test_internet_timetag.py
```
