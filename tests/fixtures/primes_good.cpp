#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::printf("usage: primes N\n");
        return 1;
    }
    const long n = std::atol(argv[1]);
    if (n < 2) {
        std::printf("0 0 0\n");
        return 0;
    }
    std::vector<bool> composite(static_cast<std::size_t>(n) + 1, false);
    long count = 0;
    long last = 0;
    std::uint64_t sum = 0;
    for (long i = 2; i <= n; ++i) {
        if (!composite[static_cast<std::size_t>(i)]) {
            ++count;
            last = i;
            sum = (sum + static_cast<std::uint64_t>(i)) % 1000000007ULL;
            for (long j = i * i; j <= n; j += i) composite[static_cast<std::size_t>(j)] = true;
        }
    }
    std::printf("%ld %llu %ld\n", count, static_cast<unsigned long long>(sum), last);
    return 0;
}
