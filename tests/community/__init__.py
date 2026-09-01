# 让 tests/community 成为包：与 tests/ai 同名的 test_retention.py 在
# rootdir 模式下会撞 module name（pytest 的 import file mismatch）。
# tests/identity 早就是包，这里照做。
