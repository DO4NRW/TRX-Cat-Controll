/**
 * RigLink Web Serial — Icom CI-V Protokoll im Browser
 * Read-Only: Frequenz, Mode, S-Meter, Scope (kein TX/PTT)
 */

class IcomCIV {
    constructor() {
        this.port = null;
        this.reader = null;
        this.writer = null;
        this.connected = false;
        this.civAddress = 0xA4; // IC-705 default
        this.ctrlAddress = 0xE0;
        this.buffer = new Uint8Array(0);
        this.scopeSpanHz = 0;
        this.scopeCenterHz = 0;
        this.scopeSpectrum = new Array(475).fill(0);

        // Callbacks
        this.onFrequency = null;
        this.onMode = null;
        this.onSMeter = null;
        this.onSpectrum = null;
        this.onConnect = null;
        this.onDisconnect = null;
        this.onPower = null;
    }

    // Known CI-V addresses
    static RIG_ADDRESSES = {
        'ic705': 0xA4,
        'ic7300': 0x94,
        'ic7610': 0x98,
        'ic9700': 0xA2,
        'ic7100': 0x88,
    };

    async connect(baudRate = 115200, stopBits = 2) {
        try {
            this.port = await navigator.serial.requestPort();
            await this.port.open({
                baudRate: baudRate,
                dataBits: 8,
                stopBits: stopBits,
                parity: 'none',
                flowControl: 'none',
            });

            this.writer = this.port.writable.getWriter();
            this.connected = true;

            if (this.onConnect) this.onConnect();

            // Start reading
            this._readLoop();

            // Scope aktivieren (IC-705: 0x27 0x10 0x01 = Scope ON)
            await this._send(0x27, 0x10, [0x01]);
            // Scope Output ON (0x27 0x11 0x01)
            await this._send(0x27, 0x11, [0x01]);

            // Start polling
            this._startPolling();

            return true;
        } catch (e) {
            console.error('Connect failed:', e);
            return false;
        }
    }

    async disconnect() {
        this.connected = false;
        this._stopPolling();

        try {
            if (this.reader) {
                try { await this.reader.cancel(); } catch (_) {}
                try { this.reader.releaseLock(); } catch (_) {}
                this.reader = null;
            }
            if (this.writer) {
                try { this.writer.releaseLock(); } catch (_) {}
                this.writer = null;
            }
            if (this.port) {
                try { await this.port.close(); } catch (_) {}
                this.port = null;
            }
        } catch (e) {
            console.warn('Disconnect error:', e);
        }

        if (this.onDisconnect) this.onDisconnect();
    }

    // Build CI-V frame
    _buildFrame(cmd, sub = null, data = []) {
        const frame = [0xFE, 0xFE, this.civAddress, this.ctrlAddress, cmd];
        if (sub !== null) frame.push(sub);
        frame.push(...data);
        frame.push(0xFD);
        return new Uint8Array(frame);
    }

    // Send command
    async _send(cmd, sub = null, data = []) {
        if (!this.writer || !this.connected) return;
        try {
            const frame = this._buildFrame(cmd, sub, data);
            await this.writer.write(frame);
        } catch (e) {
            console.error('Send error:', e);
        }
    }

    // Read loop
    async _readLoop() {
        while (this.connected && this.port?.readable) {
            const reader = this.port.readable.getReader();
            this.reader = reader;
            try {
                while (this.connected) {
                    const { value, done } = await reader.read();
                    if (done) break;
                    if (value) this._processBytes(value);
                }
            } catch (e) {
                if (this.connected) console.warn('Read error (reconnecting...):', e.message);
            } finally {
                try { reader.releaseLock(); } catch (_) {}
            }
            // Kurz warten vor Retry
            if (this.connected) await new Promise(r => setTimeout(r, 500));
        }
    }

    // Process incoming bytes
    _processBytes(newBytes) {
        // Append to buffer
        const combined = new Uint8Array(this.buffer.length + newBytes.length);
        combined.set(this.buffer);
        combined.set(newBytes, this.buffer.length);
        this.buffer = combined;

        // Extract complete frames (FE FE ... FD)
        while (true) {
            const start = this._findPattern(this.buffer, [0xFE, 0xFE]);
            if (start < 0) {
                this.buffer = new Uint8Array(0);
                break;
            }
            const end = this.buffer.indexOf(0xFD, start + 2);
            if (end < 0) {
                // Incomplete frame, keep buffer from start
                this.buffer = this.buffer.slice(start);
                break;
            }

            const frame = this.buffer.slice(start, end + 1);
            this.buffer = this.buffer.slice(end + 1);

            // Only process frames addressed to us
            if (frame.length >= 5 && frame[2] === this.ctrlAddress) {
                this._parseFrame(frame);
            }
        }
    }

    _findPattern(arr, pattern) {
        for (let i = 0; i <= arr.length - pattern.length; i++) {
            let match = true;
            for (let j = 0; j < pattern.length; j++) {
                if (arr[i + j] !== pattern[j]) { match = false; break; }
            }
            if (match) return i;
        }
        return -1;
    }

    // Parse CI-V response frame
    _parseFrame(frame) {
        if (frame.length < 5) return;
        const cmd = frame[4];
        const data = frame.slice(5, -1);
        console.log(`[CIV] cmd=0x${cmd.toString(16)} len=${data.length} data=${Array.from(data.slice(0,6)).map(b=>'0x'+b.toString(16)).join(' ')}`);

        switch (cmd) {
            case 0x03: // Frequency response
            case 0x00: // Also frequency (transceive)
                if (data.length >= 5) {
                    const freq = this._bcdToFreq(data);
                    if (this.onFrequency && freq > 0) this.onFrequency(freq);
                }
                break;

            case 0x04: // Mode response
            case 0x01: // Mode (transceive)
                if (data.length >= 1) {
                    const mode = this._parseMode(data[0]);
                    if (this.onMode && mode) this.onMode(mode);
                }
                break;

            case 0x15: // Meter readings
                if (data.length >= 3 && data[0] === 0x02) {
                    // S-Meter: sub 0x02
                    const raw = this._bcdToIntMSB(data.slice(1, 3));
                    if (this.onSMeter) this.onSMeter(raw);
                }
                break;

            case 0x14: // Levels
                if (data.length >= 3 && data[0] === 0x0A) {
                    // Power level
                    const raw = this._bcdToIntMSB(data.slice(1, 3));
                    if (this.onPower) this.onPower(raw);
                }
                break;

            case 0x27: // Scope data
                this._parseScopeFrame(frame);
                break;

            case 0xFB: // ACK
                break;
            case 0xFA: // NAK
                break;
        }
    }

    // Parse scope frame
    _parseScopeFrame(frame) {
        if (frame.length < 10) return;
        const divOrder = this._bcdByte(frame[7]);
        const divMax = this._bcdByte(frame[8]);

        if (divOrder === 1) {
            // Header division — center freq + span
            if (frame.length >= 18) {
                this.scopeCenterHz = this._bcdToFreq(frame.slice(10, 15));
                this.scopeSpanHz = this._bcdToInt(frame.slice(15, 18));
            }
            return;
        }

        // Wave data
        const waveData = frame.slice(9, -1);
        if (waveData.length === 0) return;

        if (divOrder < 2 || divOrder > 11) return;
        const offset = (divOrder - 2) * 50;

        for (let i = 0; i < waveData.length; i++) {
            const idx = offset + i;
            if (idx >= 0 && idx < 475) {
                this.scopeSpectrum[idx] = Math.min(160, waveData[i]);
            }
        }

        // Emit spectrum on last division
        if (divOrder >= divMax - 1 || divOrder === 11) {
            if (this.onSpectrum) {
                this.onSpectrum([...this.scopeSpectrum], this.scopeCenterHz, this.scopeSpanHz);
            }
        }
    }

    // BCD helpers
    _bcdByte(b) {
        return ((b >> 4) & 0x0F) * 10 + (b & 0x0F);
    }

    _bcdToFreq(data) {
        // LSB first, 5 bytes → Hz
        let result = 0;
        for (let i = 0; i < data.length; i++) {
            const lo = data[i] & 0x0F;
            const hi = (data[i] >> 4) & 0x0F;
            result += (hi * 10 + lo) * Math.pow(100, i);
        }
        return result;
    }

    _bcdToInt(data) {
        // LSB first (for span etc.)
        let result = 0;
        for (let i = 0; i < data.length; i++) {
            const lo = data[i] & 0x0F;
            const hi = (data[i] >> 4) & 0x0F;
            result += (hi * 10 + lo) * Math.pow(100, i);
        }
        return result;
    }

    _bcdToIntMSB(data) {
        // MSB first (for levels/meters)
        let result = 0;
        for (const b of data) {
            const hi = (b >> 4) & 0x0F;
            const lo = b & 0x0F;
            result = result * 100 + hi * 10 + lo;
        }
        return result;
    }

    _parseMode(byte) {
        const modes = {
            0x00: 'LSB', 0x01: 'USB', 0x02: 'AM',
            0x03: 'CW', 0x04: 'RTTY', 0x05: 'FM',
            0x07: 'CW-R', 0x08: 'RTTY-R',
        };
        return modes[byte] || null;
    }

    // Polling
    _pollTimer = null;
    _pollCount = 0;

    _startPolling() {
        this._pollCount = 0;
        this._pollTimer = setInterval(() => this._poll(), 150);
    }

    _stopPolling() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    }

    async _poll() {
        if (!this.connected) return;
        this._pollCount++;

        // Frequency (every 5th tick after initial sync)
        if (this._pollCount <= 10 || this._pollCount % 30 === 0) {
            await this._send(0x03); // Get frequency
        }

        // S-Meter (every 3rd tick)
        if (this._pollCount % 3 === 0) {
            await this._send(0x15, 0x02); // Get S-Meter
        }

        // Mode (first few ticks + every 50th)
        if (this._pollCount <= 5 || this._pollCount % 50 === 0) {
            await this._send(0x04); // Get mode
        }

        // Power (first few ticks)
        if (this._pollCount <= 5) {
            await this._send(0x14, 0x0A); // Get power
        }
    }
}

// Export
window.IcomCIV = IcomCIV;
