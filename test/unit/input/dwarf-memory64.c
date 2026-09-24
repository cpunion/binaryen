__attribute__((always_inline)) static inline long add_seven(long input) {
  long local = input + 7;
  return local;
}

__attribute__((noinline)) long debug_probe(long input) {
  long before = add_seven(input);
  if (input > 0) {
    before += add_seven(input + 1);
  }
  return before;
}
