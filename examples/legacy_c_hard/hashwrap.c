/* hashwrap.c - 32-bit FNV-1a hash and checksum utilities relying on unsigned wraparound.
 * Trap: arithmetic must stay 32-bit unsigned and 8-bit unsigned; widening to 64-bit changes output.
 */
#include <stdio.h>
#include <string.h>

typedef unsigned int u32;
typedef unsigned char u8;

static u32 fnv1a(const char *s)
{
    u32 h = 2166136261u;
    while (*s) {
        h ^= (u8)*s++;
        h *= 16777619u;
    }
    return h;
}

int main(int argc, char **argv)
{
    int i;
    for (i = 1; i < argc; i++) {
        const char *s = argv[i];
        u8 sum8 = 0;
        u32 rot = 0;
        size_t j;
        for (j = 0; j < strlen(s); j++) {
            sum8 += (u8)s[j];
            rot = (rot << 5) | (rot >> 27);
            rot += (u32)s[j];
        }
        printf("%s fnv=%08x sum8=%u rot=%u neg=%u\n", s, fnv1a(s), sum8, rot, 0u - (u32)strlen(s));
    }
    return argc > 1 ? 0 : 4;
}
