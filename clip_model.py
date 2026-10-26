"""CLIP without PyTorch: tokenizer, image preprocessing and the two ONNX encoders.

Plain Python + NumPy + Pillow + onnxruntime, no bpy: runs on the worker thread.
The tokenizer is a port of open_clip's SimpleTokenizer (originally OpenAI's,
MIT licence) using only the standard library.
"""

import gzip
import html
import os
import re
import unicodedata
from functools import lru_cache

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
VOCAB_PATH = os.path.join(HERE, "bpe_simple_vocab_16e6.txt.gz")
CONTEXT_LENGTH = 77
IMAGE_SIZE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

# ------------------------------------------------------------------ #
# Tokenizer
# ------------------------------------------------------------------ #

# open_clip uses the third-party `regex` module for \p{L} (any letter) and
# \p{N} (any number). These are the closest standard-library equivalents.
_LETTERS = r"[^\W\d_]+"
_DIGIT = r"\d"
_OTHER = r"(?:[^\s\w]|_)+"
_PATTERN = re.compile(
    r"<start_of_text>|<end_of_text>|'s|'t|'re|'ve|'m|'ll|'d|"
    + _LETTERS + "|" + _DIGIT + "|" + _OTHER,
    re.IGNORECASE,
)
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
                         "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"'})


@lru_cache()
def _bytes_to_unicode():
    """CLIP maps every byte to a printable character before applying merges."""
    bs = (list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1))
          + list(range(ord("®"), ord("ÿ") + 1)))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, (chr(c) for c in cs)))


def _clean(text):
    """Stand-in for ftfy.fix_text + open_clip's 'lower' cleaning."""
    text = unicodedata.normalize("NFC", text).translate(_QUOTES)
    text = html.unescape(html.unescape(text)).strip()
    return " ".join(text.split()).lower()


class Tokenizer:
    def __init__(self, vocab_path=VOCAB_PATH):
        self.byte_encoder = _bytes_to_unicode()
        with gzip.open(vocab_path) as f:
            merges = f.read().decode("utf-8").split("\n")[1:49152 - 256 - 2 + 1]
        merges = [tuple(m.split()) for m in merges]
        vocab = list(self.byte_encoder.values())
        vocab += [v + "</w>" for v in vocab]
        vocab += ["".join(m) for m in merges]
        vocab += ["<start_of_text>", "<end_of_text>"]
        self.encoder = {piece: i for i, piece in enumerate(vocab)}
        self.ranks = {m: i for i, m in enumerate(merges)}
        self.sot = self.encoder["<start_of_text>"]   # 49406
        self.eot = self.encoder["<end_of_text>"]     # 49407
        self.cache = {}

    def _bpe(self, token):
        """Repeatedly merge the highest-priority adjacent pair of pieces."""
        if token in self.cache:
            return self.cache[token]
        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        while len(word) > 1:
            pairs = {(word[i], word[i + 1]) for i in range(len(word) - 1)}
            best = min(pairs, key=lambda p: self.ranks.get(p, float("inf")))
            if best not in self.ranks:
                break
            merged, i = [], 0
            while i < len(word):
                if i < len(word) - 1 and (word[i], word[i + 1]) == best:
                    merged.append(word[i] + word[i + 1])
                    i += 2
                else:
                    merged.append(word[i])
                    i += 1
            word = tuple(merged)
        self.cache[token] = word
        return word

    def encode(self, text):
        ids = []
        for token in _PATTERN.findall(_clean(text)):
            token = "".join(self.byte_encoder[b] for b in token.encode("utf-8"))
            ids.extend(self.encoder[piece] for piece in self._bpe(token))
        return ids

    def __call__(self, texts):
        """List of strings -> int64 array [len(texts), 77], zero-padded."""
        out = np.zeros((len(texts), CONTEXT_LENGTH), dtype=np.int64)
        for row, text in enumerate(texts):
            ids = [self.sot] + self.encode(text) + [self.eot]
            if len(ids) > CONTEXT_LENGTH:
                ids = ids[:CONTEXT_LENGTH]
                ids[-1] = self.eot  # always end with the end marker
            out[row, :len(ids)] = ids
        return out


# ------------------------------------------------------------------ #
# Image preprocessing (matches open_clip's Resize -> CenterCrop -> Normalize)
# ------------------------------------------------------------------ #

def preprocess(img):
    """PIL RGB image -> float32 array [3, 224, 224]."""
    w, h = img.size
    if w <= h:  # shorter side becomes 224, same rounding as torchvision
        size = (IMAGE_SIZE, int(IMAGE_SIZE * h / w))
    else:
        size = (int(IMAGE_SIZE * w / h), IMAGE_SIZE)
    img = img.resize(size, Image.Resampling.BICUBIC)

    w, h = img.size
    left = int(round((w - IMAGE_SIZE) / 2.0))
    top = int(round((h - IMAGE_SIZE) / 2.0))
    img = img.crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE))

    arr = np.asarray(img, dtype=np.float32) / 255.0   # [224, 224, 3], values 0..1
    arr = (arr - MEAN) / STD                          # per-colour normalize
    return arr.transpose(2, 0, 1)                     # -> [3, 224, 224]


# ------------------------------------------------------------------ #
# The model
# ------------------------------------------------------------------ #

def _unit(v):
    return v / np.linalg.norm(v, axis=1, keepdims=True)


class ClipModel:
    def __init__(self, image_path, text_path):
        import onnxruntime as ort  # imported here so the tokenizer works without it
        opts = ["CPUExecutionProvider"]
        self.image_session = ort.InferenceSession(image_path, providers=opts)
        self.text_session = ort.InferenceSession(text_path, providers=opts)
        self.tokenizer = Tokenizer()

    def encode_texts(self, texts):
        """List of strings -> unit vectors [len(texts), 512]."""
        out = self.text_session.run(None, {"tokens": self.tokenizer(texts)})[0]
        return _unit(out)

    def encode_images(self, images, batch_size=16):
        """List of PIL RGB images -> unit vectors [len(images), 512]."""
        vectors = []
        for start in range(0, len(images), batch_size):
            batch = np.stack([preprocess(im) for im in images[start:start + batch_size]])
            vectors.append(self.image_session.run(None, {"pixels": batch})[0])
        return _unit(np.concatenate(vectors))
