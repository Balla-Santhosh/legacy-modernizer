/* primes.c - sieve of Eratosthenes; prints count, sum mod 1e9+7 and largest prime <= N. */
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[])
{
    long n, i, j, count = 0, last = 0;
    unsigned long long sum = 0;
    char *composite;
    if (argc != 2) { printf("usage: primes N\n"); return 1; }
    n = atol(argv[1]);
    if (n < 2) { printf("0 0 0\n"); return 0; }
    composite = (char *)calloc(n + 1, 1);
    for (i = 2; i <= n; i++) {
        if (!composite[i]) {
            count++;
            last = i;
            sum = (sum + i) % 1000000007ULL;
            for (j = i * i; j <= n; j += i) composite[j] = 1;
        }
    }
    printf("%ld %llu %ld\n", count, sum, last);
    free(composite);
    return 0;
}
