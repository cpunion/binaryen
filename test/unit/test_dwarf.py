import os
import shutil
import subprocess
import tempfile

from scripts.test import shared

from . import utils


def read_uleb(data, offset):
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7f) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def write_uleb(value):
    data = bytearray()
    while value >= 0x80:
        data.append((value & 0x7f) | 0x80)
        value >>= 7
    data.append(value)
    return bytes(data)


def custom_section(data, name):
    offset = 8
    while offset < len(data):
        kind = data[offset]
        size, payload = read_uleb(data, offset + 1)
        end = payload + size
        if kind == 0:
            name_size, contents = read_uleb(data, payload)
            section_name = data[contents:contents + name_size].decode()
            if section_name == name:
                return data[contents + name_size:end]
        offset = end
    raise ValueError(name)


def replace_custom_section(data, name, replacement):
    offset = 8
    while offset < len(data):
        kind = data[offset]
        size, payload = read_uleb(data, offset + 1)
        end = payload + size
        if kind == 0:
            name_size, contents = read_uleb(data, payload)
            section_name = data[contents:contents + name_size].decode()
            if section_name == name:
                name_bytes = data[contents:contents + name_size]
                new_payload = write_uleb(name_size) + name_bytes + replacement
                return (data[:offset] + b'\0' +
                        write_uleb(len(new_payload)) + new_payload + data[end:])
        offset = end
    raise ValueError(name)


def append_custom_section(data, name, contents):
    name_bytes = name.encode()
    payload = write_uleb(len(name_bytes)) + name_bytes + contents
    return data + b'\0' + write_uleb(len(payload)) + payload


class DWARFTest(utils.BinaryenTestCase):
    def test_memory64_address_width(self):
        # Regenerate the checked-in input from dwarf-memory64.c with:
        # clang -target wasm64-unknown-unknown -O1 -g -gdwarf-4 \
        #   -fdebug-compilation-dir=/binaryen -c dwarf-memory64.c -o input.o
        # wasm-ld -mwasm64 --no-entry --export=debug_probe input.o -o memory64.wasm
        source = self.input_path(os.path.join('dwarf', 'memory64.wasm'))
        dwarfdump = shutil.which('llvm-dwarfdump')
        with tempfile.TemporaryDirectory() as temp_dir:
            for name, args in [('roundtrip', ['--roundtrip']),
                               ('asyncify', ['--asyncify'])]:
                output = os.path.join(temp_dir, name + '.wasm')
                shared.run_process(shared.WASM_OPT +
                                   [source, '-g', *args, '-o', output])
                dump = shared.run_process(shared.WASM_OPT +
                                          [output, '--dwarfdump'],
                                          capture_output=True).stdout
                self.assertIn('debug_probe', dump)
                if dwarfdump:
                    verify = subprocess.run([dwarfdump, '--verify', output],
                                            capture_output=True, text=True)
                    diagnostics = verify.stdout + verify.stderr
                    self.assertEqual(verify.returncode, 0, diagnostics)
                    self.assertNotIn('mismatching address size', diagnostics)
                    self.assertIn('No errors.', diagnostics)

    def test_memory64_dwarf64_line_discriminator(self):
        source = self.input_path(os.path.join('dwarf', 'memory64.wasm'))
        with open(source, 'rb') as f:
            wasm = f.read()
        line = custom_section(wasm, '.debug_line')
        prologue_length = int.from_bytes(line[6:10], 'little')
        opcodes = 10 + prologue_length
        set_address = line.index(b'\x00\x09\x02', opcodes)
        first_row = set_address + 11  # opcode, length, subopcode, 8-byte address
        discriminator = b'\x00\x03\x04\xac\x02'  # DW_LNE_set_discriminator 300
        line = line[:first_row] + discriminator + line[first_row:]
        # Convert the line table to DWARF64, independently of the CU's
        # address size and the DWARF32 format used by .debug_info.
        body_length = len(line)  # four more prologue bytes replace four prefix bytes
        line = (b'\xff' * 4 + body_length.to_bytes(8, 'little') +
                line[4:6] + prologue_length.to_bytes(8, 'little') + line[10:])
        wasm = replace_custom_section(wasm, '.debug_line', line)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, 'input.wasm')
            output_file = os.path.join(temp_dir, 'output.wasm')
            with open(input_file, 'wb') as f:
                f.write(wasm)
            shared.run_process(shared.WASM_OPT +
                               [input_file, '--roundtrip', '-g', '-o', output_file])
            with open(output_file, 'rb') as f:
                output = f.read()
            output_line = custom_section(output, '.debug_line')
            self.assertEqual(output_line[:4], b'\xff' * 4)
            self.assertEqual(int.from_bytes(output_line[4:12], 'little'),
                             len(output_line) - 12)
            self.assertIn(discriminator, output_line)
            dwarfdump = shutil.which('llvm-dwarfdump')
            if dwarfdump:
                verify = subprocess.run([dwarfdump, '--verify', output_file],
                                        capture_output=True, text=True)
                self.assertEqual(verify.returncode, 0,
                                 verify.stdout + verify.stderr)
                lines = subprocess.run([dwarfdump, '--debug-line', output_file],
                                       capture_output=True, text=True)
                self.assertIn('DWARF64', lines.stdout)
                self.assertIn('300', lines.stdout)

    def test_memory64_loc_value_with_32_bit_all_ones(self):
        source = self.input_path(os.path.join('dwarf', 'memory64.wasm'))
        with open(source, 'rb') as f:
            wasm = f.read()
        loc = custom_section(wasm, '.debug_loc')
        # A 64-bit value with only its low 32 bits set is a normal location,
        # not a base-address-selection marker or list terminator.
        loc = ((0xffffffff).to_bytes(8, 'little') +
               (0x100000000).to_bytes(8, 'little') + loc[16:])
        wasm = replace_custom_section(wasm, '.debug_loc', loc)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, 'input.wasm')
            output_file = os.path.join(temp_dir, 'output.wasm')
            with open(input_file, 'wb') as f:
                f.write(wasm)
            shared.run_process(shared.WASM_OPT +
                               [input_file, '--roundtrip', '-g', '-o', output_file])
            with open(output_file, 'rb') as f:
                output_loc = custom_section(f.read(), '.debug_loc')
            self.assertEqual(len(output_loc), len(loc))
            self.assertEqual(output_loc[:16],
                             (1).to_bytes(8, 'little') * 2)

    def test_memory64_range_outside_binary_offset(self):
        source = self.input_path(os.path.join('dwarf', 'memory64.wasm'))
        with open(source, 'rb') as f:
            wasm = f.read()
        ranges = ((0x100000003).to_bytes(8, 'little') +
                  (0x100000004).to_bytes(8, 'little') + b'\0' * 16)
        wasm = append_custom_section(wasm, '.debug_ranges', ranges)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, 'input.wasm')
            output_file = os.path.join(temp_dir, 'output.wasm')
            with open(input_file, 'wb') as f:
                f.write(wasm)
            shared.run_process(shared.WASM_OPT +
                               [input_file, '--roundtrip', '-g', '-o', output_file])
            with open(output_file, 'rb') as f:
                output_ranges = custom_section(f.read(), '.debug_ranges')
            self.assertEqual(output_ranges[:16],
                             (1).to_bytes(8, 'little') * 2)

    def test_tombstone_roundtrip(self):
        def custom_section(name, contents):
            name = name.encode()
            payload = bytes([len(name)]) + name + contents
            self.assertLess(len(payload), 128)
            return bytes([0, len(payload)]) + payload

        # A minimal DWARF v4 unit whose compile unit and subprogram both use
        # the all-ones dead-address sentinel for DW_AT_low_pc.
        sections = {
            '.debug_abbrev': '011101030e110112060000022e0011011206030e000000',
            '.debug_info': ('22000000040000000000040100000000ffffffff'
                            '0300000002ffffffff030000000f00000000'),
            '.debug_str': '746573742d636c616e672e63707000666f6f00',
        }
        wasm = bytes.fromhex('0061736d01000000')
        for name, contents in sections.items():
            wasm += custom_section(name, bytes.fromhex(contents))

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, 'input.wasm')
            output_file = os.path.join(temp_dir, 'output.wasm')
            with open(input_file, 'wb') as f:
                f.write(wasm)
            shared.run_process(shared.WASM_OPT +
                               [input_file, '--roundtrip', '-g',
                                '-o', output_file])
            dump = shared.run_process(shared.WASM_OPT +
                                      [output_file, '--dwarfdump'],
                                      capture_output=True).stdout
            self.assertEqual(dump.count('0x00000000ffffffff'), 2)

    def test_no_crash(self):
        # run dwarf processing on some interesting large files, too big to be
        # worth putting in passes where the text output would be massive. We
        # just check that no assertion are hit.
        path = self.input_path('dwarf')
        for name in os.listdir(path):
            args = [os.path.join(path, name)] + \
                   ['-g', '--dwarfdump', '--roundtrip', '--dwarfdump']
            shared.run_process(shared.WASM_OPT + args, capture_output=True)

    def test_dwarf_incompatibility(self):
        warning = 'not fully compatible with DWARF'
        path = self.input_path(os.path.join('dwarf', 'cubescript.wasm'))
        args = [path, '-g']
        # flatten warns
        err = shared.run_process(shared.WASM_OPT + args + ['--flatten'], stderr=subprocess.PIPE).stderr
        self.assertIn(warning, err)
        # safe passes do not
        err = shared.run_process(shared.WASM_OPT + args + ['--metrics'], stderr=subprocess.PIPE).stderr
        self.assertNotIn(warning, err)

    def test_strip_dwarf_and_opts(self):
        # some optimizations are disabled when DWARF is present (as they would
        # destroy it). we scan the wasm to see if there is any DWARF when
        # making the decision whether to run them. this test checks that we also
        # check if --strip* is being run, which would remove the DWARF anyhow
        path = self.input_path(os.path.join('dwarf', 'cubescript.wasm'))
        # strip the DWARF, then run all the opts to check as much as possible
        args = [path, '--strip-dwarf', '-Oz']
        # run it normally, without -g. in this case no DWARF will be preserved
        # in a trivial way
        shared.run_process(shared.WASM_OPT + args + ['-o', 'a.wasm'])
        # run it with -g. in this case we need to be clever as described above,
        # and see --strip-dwarf removes the need for DWARF
        shared.run_process(shared.WASM_OPT + args + ['-o', 'b.wasm', '-g'])
        # run again on the last output without -g, as we don't want the names
        # section to skew the results
        shared.run_process(shared.WASM_OPT + ['b.wasm', '-o', 'c.wasm'])
        # compare the sizes. there might be a tiny difference in size to to
        # minor roundtrip changes, so ignore up to a tiny %
        a_size = os.path.getsize('a.wasm')
        c_size = os.path.getsize('c.wasm')
        self.assertLess((100 * abs(a_size - c_size)) / c_size, 1)
