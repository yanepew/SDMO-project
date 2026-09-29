# Code from https://github.com/oconnor663/pure_python_salsa_chacha/blob/main/chacha20/pure_chacha20.py

from legacy_memory_controller import MemoryController

# input in temp_in, output to out
def mask32(mem: MemoryController):
    mem["out"] = mem["temp_in"] & 0xFFFFFFFF

# input in pair, output to out
def add32(mem: MemoryController):
    with mem.auto_alloc("temp_in", mem["pair"][0] + mem["pair"][1]):
        mask32(mem)

# input in pair, output to out
def left_rotate(mem: MemoryController):
    with mem.auto_alloc("temp_in", mem["pair"][0] << mem["pair"][1]):
        mask32()
        mem["out"] = mem["out"] | (mem["pair"][0] >> (32 - mem["pair"][1]))

# per_block is expected to store the block to permute and mem["abcd"] should have the indices
def quarter_round(mem: MemoryController):
    mem.allocate_empty_variables("pair", "out")
    mem["pair"] = (mem["per_block"][mem["abcd"][0]], mem["per_block"][mem["abcd"][1]])
    add32(mem)
    mem["per_block"][mem["abcd"][0]] = mem["out"]
    mem["per_block"][mem["abcd"][3]] ^= mem["per_block"][mem["abcd"][0]]
    mem["pair"] = (mem["per_block"][mem["abcd"][3]], 16)
    left_rotate(mem)
    mem["per_block"][mem["abcd"][3]] = mem["out"]
    mem["pair"] = (mem["per_block"][mem["abcd"][2]], mem["per_block"][mem["abcd"][3]])
    add32(mem)
    mem["per_block"][mem["abcd"][2]] = mem["out"]
    mem["per_block"][mem["abcd"][1]] ^= mem["per_block"][mem["abcd"][2]]
    mem["pair"] = (mem["per_block"][mem["abcd"][1]], 12)
    left_rotate(mem)
    mem["per_block"][mem["abcd"][1]] = mem["out"]
    mem["pair"] = (mem["per_block"][mem["abcd"][0]], mem["per_block"][mem["abcd"][1]])
    add32(mem)
    mem["per_block"][mem["abcd"][0]] = mem["out"]
    mem["per_block"][mem["abcd"][3]] ^= mem["per_block"][mem["abcd"][0]]
    mem["pair"] = (mem["per_block"][mem["abcd"][3]], 8)
    left_rotate(mem)
    mem["per_block"][mem["abcd"][3]] = mem["out"]
    mem["pair"] = (mem["per_block"][mem["abcd"][2]], mem["per_block"][mem["abcd"][3]])
    add32(mem)
    mem["per_block"][mem["abcd"][2]] = mem["out"]
    mem["per_block"][mem["abcd"][1]] ^= mem["per_block"][mem["abcd"][2]]
    mem["pair"] = (mem["per_block"][mem["abcd"][1]], 7)
    left_rotate(mem)
    mem["per_block"][mem["abcd"][1]] = mem["out"]
    mem.update_memory_use("per_block")
    mem.deallocate_variables("pair", "out")

# per_block in memory is permuted
def chacha20_permute(mem: MemoryController):
    with mem.auto_alloc("abcd", None):
        for _ in range(10):
            mem["abcd"] = (0, 4, 8, 12) # column 1
            quarter_round(mem)
            mem["abcd"] = (1, 5, 9, 13) # column 2
            quarter_round(mem)
            mem["abcd"] = (2, 6, 10, 14) # column 3
            quarter_round(mem)
            mem["abcd"] = (3, 7, 11, 15) # column 4
            quarter_round(mem)
            mem["abcd"] = (0, 5, 10, 15) # diagonal 1
            quarter_round(mem)
            mem["abcd"] = (1, 6, 11, 12) # diagonal 2
            quarter_round(mem)
            mem["abcd"] = (2, 7, 8, 13) # diagonal 3
            quarter_round(mem)
            mem["abcd"] = (3, 4, 9, 14) # diagonal 4
            quarter_round(mem)

# bytes read from wfb_in and so should mem["wfb_res_key"] key for result 
def words_from_bytes(mem: MemoryController):
    assert len(mem["wfb_in"]) % 4 == 0
    mem[mem["wfb_res_key"]] = [int.from_bytes(mem["wfb_in"][4 * i : 4 * i + 4], "little") for i in range(len(mem["wfb_in"]) // 4)]

def bytes_from_words(w):
    return b"".join(word.to_bytes(4, "little") for word in w)

# This is the IETF (RFC 7539) version of ChaCha20, with a 96-bit nonce.
def chacha20_block(key, nonce, blocknum):
    # This implementation doesn't support 16-byte keys.
    assert len(key) == 32
    assert len(nonce) == 12
    assert blocknum < 2 ** 32
    constant_words = words_from_bytes(b"expand 32-byte k")
    key_words = words_from_bytes(key)
    nonce_words = words_from_bytes(nonce)
    # fmt: off
    original_block = [
        constant_words[0],  constant_words[1],  constant_words[2],  constant_words[3],
        key_words[0],       key_words[1],       key_words[2],       key_words[3],
        key_words[4],       key_words[5],       key_words[6],       key_words[7],
        mask32(blocknum),   nonce_words[0],     nonce_words[1],     nonce_words[2],
    ]
    # fmt: on
    permuted_block = list(original_block)
    chacha20_permute(permuted_block)
    for i in range(len(permuted_block)):
        permuted_block[i] = add32(permuted_block[i], original_block[i])
    return bytes_from_words(permuted_block)

def chacha20_stream(key, nonce, length):
    output = bytearray()
    blocknum = 0
    while length > 0:
        block = chacha20_block(key, nonce, blocknum)
        take = min(length, len(block))
        output.extend(block[:take])
        length -= take
        blocknum += 1
    return output

# expects key and nonce to be in memory and should have derived_key variable
def hchacha20(mem: MemoryController):
    mem.allocate_empty_variables("constant_words", "key_words", "input_words")

    mem.allocate_variable("wfb_in", b"expand 32-byte k")
    mem.allocate_variable("wfb_res_key", "constant_words")
    words_from_bytes(mem)

    mem["wfb_in"] = mem["key"]
    mem["wfb_res_key"] = "key_words"
    words_from_bytes(mem)

    mem["wfb_in"] = mem["nonce"][:16]
    mem["wfb_res_key"] = "input_words"
    words_from_bytes(mem)
    # fmt: off
    with mem.auto_alloc("per_block", None):
        mem["per_block"] = [
            mem["constant_words"][0], mem["constant_words"][1], mem["constant_words"][2], mem["constant_words"][3],
            mem["key_words"][0],      mem["key_words"][1],      mem["key_words"][2],      mem["key_words"][3],
            mem["key_words"][4],      mem["key_words"][5],      mem["key_words"][6],      mem["key_words"][7],
            mem["input_words"][0],    mem["input_words"][1],    mem["input_words"][2],    mem["input_words"][3]
        ]
        mem.deallocate_variables("wfb_in", "wfb_res_key", "constant_words", "key_words", "input_words")
        # fmt: on
        chacha20_permute(mem)
        outputs = mem["per_block"][0:4] + mem["per_block"][12:16]
        return bytes_from_words(outputs)
            
# expects key, nonce and message to be in memory and should similarly have a stream variable
def xchacha20_stream(mem: MemoryController):
    with mem.auto_alloc("derived_key", None):
        hchacha20(mem) #set derived_key
        chacha20_stream(derived_key, b"\0\0\0\0" + nonce[16:], length) #set stream

# expects key, nonce and message to be in memory and should similarly have a ciphertext variable
def xchacha20_xor(mem: MemoryController):
    # This implementation doesn't support 16-byte keys.
    assert len(mem["key"]) == 32
    assert len(mem["nonce"]) == 24
    with mem.auto_alloc("stream", None):
        xchacha20_stream(mem) #set stream
        mem["ciphertext"] = bytes(x ^ y for x, y in zip(mem["message"], mem["stream"]))
