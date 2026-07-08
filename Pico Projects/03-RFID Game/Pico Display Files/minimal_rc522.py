from machine import Pin, SPI
import time

# --- MFRC522 register addresses (from the NXP datasheet) ---
CommandReg    = 0x01
ComIrqReg     = 0x04
ErrorReg      = 0x06
FIFODataReg   = 0x09
FIFOLevelReg  = 0x0A
BitFramingReg = 0x0D
ModeReg       = 0x11
TxControlReg  = 0x14
TxASKReg      = 0x15
TModeReg      = 0x2A
TPrescalerReg = 0x2B
TReloadRegH   = 0x2C
TReloadRegL   = 0x2D

PCD_IDLE       = 0x00
PCD_TRANSCEIVE = 0x0C
PCD_RESET      = 0x0F

PICC_REQIDL   = 0x26  # "is anyone there?" (REQA)
PICC_ANTICOLL = 0x93  # anti-collision, cascade level 1


class MinimalRC522:
    def __init__(self, spi, cs, rst):
        self.spi = spi
        self.cs = cs
        self.rst = rst
        self.cs.value(1)
        self.rst.value(1)
        self._init_reader()

    # --- low-level register access ---
    def _write(self, reg, val):
        self.cs.value(0)
        self.spi.write(bytes([(reg << 1) & 0x7E, val]))
        self.cs.value(1)

    def _read(self, reg):
        self.cs.value(0)
        self.spi.write(bytes([((reg << 1) & 0x7E) | 0x80]))
        result = self.spi.read(1)
        self.cs.value(1)
        return result[0]

    def _set_bits(self, reg, mask):
        self._write(reg, self._read(reg) | mask)

    def _clear_bits(self, reg, mask):
        self._write(reg, self._read(reg) & (~mask & 0xFF))

    # --- setup ---
    def _init_reader(self):
        self._write(CommandReg, PCD_RESET)
        time.sleep_ms(50)
        self._write(TModeReg, 0x8D)
        self._write(TPrescalerReg, 0x3E)
        self._write(TReloadRegL, 30)
        self._write(TReloadRegH, 0)
        self._write(TxASKReg, 0x40)   # force 100% ASK modulation
        self._write(ModeReg, 0x3D)
        self._antenna_on()

    def _antenna_on(self):
        if not (self._read(TxControlReg) & 0x03):
            self._set_bits(TxControlReg, 0x03)

    # --- talking to a tag ---
    def _transceive(self, data):
        self._write(CommandReg, PCD_IDLE)
        self._write(ComIrqReg, 0x7F)          # clear all interrupt flags
        self._set_bits(FIFOLevelReg, 0x80)    # flush FIFO

        for b in data:
            self._write(FIFODataReg, b)

        self._write(CommandReg, PCD_TRANSCEIVE)
        self._set_bits(BitFramingReg, 0x80)   # start send

        for _ in range(2000):                 # wait for finish or time out
            if self._read(ComIrqReg) & 0x30:  # RxIRq or IdleIRq set
                break
        self._clear_bits(BitFramingReg, 0x80)

        if self._read(ErrorReg) & 0x1B:       # a real error bit is set
            return None

        n = self._read(FIFOLevelReg)
        return bytes(self._read(FIFODataReg) for _ in range(n))

    def request(self):
        """True if a tag is in range."""
        self._write(BitFramingReg, 0x07)      # last byte: only 7 bits valid
        resp = self._transceive([PICC_REQIDL])
        self._write(BitFramingReg, 0x00)
        return resp is not None and len(resp) == 2

    def read_uid(self):
        """Returns the tag's 4-byte UID, or None if no valid read."""
        resp = self._transceive([PICC_ANTICOLL, 0x20])
        if resp is None or len(resp) != 5:
            return None
        uid, checksum = resp[:4], resp[4]
        if (uid[0] ^ uid[1] ^ uid[2] ^ uid[3]) != checksum:
            return None
        return uid