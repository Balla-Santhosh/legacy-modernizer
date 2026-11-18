/* bits.c - bit-twiddling report for unsigned 16- and 32-bit values.
 * Trap: widths matter (unsigned short promotion, 32-bit rotate, ~ on small types).
 */
#include <stdio.h>
#include <stdlib.h>

static int popcount(unsigned int x)
{
    int c = 0;
    while (x) { x &= x - 1; c++; }
    return c;
}

static unsigned int reverse32(unsigned int x)
{
    unsigned int r = 0;
    int i;
    for (i = 0; i < 32; i++) { r = (r << 1) | (x & 1u); x >>= 1; }
    return r;
}

static void binary16(unsigned short v)
{
    int i;
    for (i = 15; i >= 0; i--) putchar((v >> i) & 1 ? '1' : '0');
}

int main(int argc, char **argv)
{
    int i;
    for (i = 1; i < argc; i++) {
        unsigned int x = (unsigned int)strtoul(argv[i], NULL, 0);
        unsigned short s = (unsigned short)x;
        unsigned short ns = ~s;
        printf("%s: pop=%d rev=%08x rotl3=%08x lowbit=%u ", argv[i], popcount(x), reverse32(x),
               (x << 3) | (x >> 29), x & (0u - x));
        binary16(s);
        printf(" not16=%u notint=%d\n", ns, ~s);
    }
    return 0;
}
