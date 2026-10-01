# Code from https://github.com/oconnor663/pure_python_salsa_chacha/blob/main/chacha20/pure_chacha20.py

from device.legacy_memory_controller import MemoryController

# input in mask_in, output to out
def mask32(mem: MemoryController):
    mem["out"] = mem["mask_in"] & 0xFFFFFFFF

# input in pair, output to out
def add32(mem: MemoryController):
    with mem.auto_alloc("mask_in", mem["pair"][0] + mem["pair"][1]):
        mask32(mem)

# input in pair, output to out
def left_rotate(mem: MemoryController):
    with mem.auto_alloc("mask_in", mem["pair"][0] << mem["pair"][1]):
        mask32(mem)
        mem["out"] = mem["out"] | (mem["pair"][0] >> (32 - mem["pair"][1]))

# per_block is expected to store the block to permute and mem["abcd"] should have the indices. pair and out should exist in memory
def quarter_round(mem: MemoryController):
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

# per_block in memory is permuted, expects pair and out to exist in memory
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

# bytes read from wfb_in and outputs to mem["wfb_res_key"] 
def words_from_bytes(mem: MemoryController):
    assert len(mem["wfb_in"]) % 4 == 0
    mem[mem["wfb_res_key"]] = [int.from_bytes(mem["wfb_in"][4 * i : 4 * i + 4], "little") for i in range(len(mem["wfb_in"]) // 4)]

#reads words from bfw_in and outputs to mem["bfw_res_key"]
def bytes_from_words(mem: MemoryController):
    mem[mem["bfw_res_key"]] = b"".join(word.to_bytes(4, "little") for word in mem["bfw_in"])

#reads derived_key, nonce and blocknum from memory and writes to block
# This is the IETF (RFC 7539) version of ChaCha20, with a 96-bit nonce.
def chacha20_block(mem: MemoryController):
    # This implementation doesn't support 16-byte keys.
    assert mem["blocknum"] < 2 ** 32
    mem.alloc_empty_vars("constant_words", "key_words", "nonce_words")
    
    mem.alloc_var("wfb_in", b"expand 32-byte k")
    mem.alloc_var("wfb_res_key", "constant_words")
    words_from_bytes(mem)

    mem["wfb_in"] = mem["derived_key"]
    mem["wfb_res_key"] = "key_words"
    words_from_bytes(mem)

    mem["wfb_in"] = b"\0\0\0\0" + mem["nonce"][16:]
    mem["wfb_res_key"] = "nonce_words"
    words_from_bytes(mem)

    mem.dealloc_vars("wfb_in", "wfb_res_key")

    # fmt: off
    with mem.auto_alloc_empty_vars("o_block", "per_block", "pair", "out"):
        with mem.auto_alloc("mask_in", mem["blocknum"]):
            mask32(mem)
        mem["o_block"] = [
            mem["constant_words"][0], mem["constant_words"][1], mem["constant_words"][2], mem["constant_words"][3],
            mem["key_words"][0],      mem["key_words"][1],      mem["key_words"][2],      mem["key_words"][3],
            mem["key_words"][4],      mem["key_words"][5],      mem["key_words"][6],      mem["key_words"][7],
            mem["out"],               mem["nonce_words"][0],    mem["nonce_words"][1],    mem["nonce_words"][2],
        ]
        mem.dealloc_vars("constant_words", "key_words", "nonce_words")
        # fmt: on
        mem["per_block"] = list(mem["o_block"])
        chacha20_permute(mem)
        for i in range(len(mem["per_block"])):
            mem["pair"] = (mem["per_block"][i], mem["o_block"][i])
            add32(mem)
            mem["per_block"][i] = mem["out"]
            mem.update_memory_use("per_block")
        with mem.auto_alloc_vars(("bfw_in", mem["per_block"]), ("bfw_res_key", "block")):
            bytes_from_words(mem)

# reads key, nonce and message, outputs to stream
def chacha20_stream(mem: MemoryController):
    mem["stream"] = bytearray()
    mem.alloc_var("len", len(mem["message"]))
    mem.alloc_var("blocknum", 0)
    while mem["len"] > 0:
        with mem.auto_alloc_empty_vars("block", "take"):
            chacha20_block(mem)
            mem["take"] = min(mem["len"], len(mem["block"]))
            mem["stream"].extend(mem["block"][:mem["take"]])
            mem.update_memory_use("stream")
            mem["len"] -= mem["take"]
            mem["blocknum"] += 1
    mem.dealloc_vars("len", "blocknum")

# reads key and nonce from memory and outputs to derived_key
def hchacha20(mem: MemoryController):
    mem.alloc_empty_vars("constant_words", "key_words", "input_words")

    mem.alloc_var("wfb_in", b"expand 32-byte k")
    mem.alloc_var("wfb_res_key", "constant_words")
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
        mem.dealloc_vars("wfb_in", "wfb_res_key", "constant_words", "key_words", "input_words")
        # fmt: on
        with mem.auto_alloc_empty_vars("pair", "out"):
            chacha20_permute(mem)
        with mem.auto_alloc("bfw_in", mem["per_block"][0:4] + mem["per_block"][12:16]):
            with mem.auto_alloc("bfw_res_key", "derived_key"): #write directly to derived_key
                bytes_from_words(mem)
            
# reads key, nonce and message from memory and outputs to stream
def xchacha20_stream(mem: MemoryController):
    with mem.auto_alloc("derived_key", None):
        hchacha20(mem) #set derived_key
        chacha20_stream(mem) #set stream

# reads key, nonce and message from memory and writes to ciphertext
def xchacha20_xor(mem: MemoryController):
    # This implementation doesn't support 16-byte keys.
    assert len(mem["key"]) == 32
    assert len(mem["nonce"]) == 24
    with mem.auto_alloc("stream", None):
        xchacha20_stream(mem) #set stream
        mem["ciphertext"] = bytes(x ^ y for x, y in zip(mem["message"], mem["stream"]))
