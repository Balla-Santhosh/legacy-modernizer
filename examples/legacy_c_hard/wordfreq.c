/* wordfreq.c - counts word frequencies with a hand-rolled chained hash table.
 * Prints words with count >= MIN (arg, default 2) in first-seen order, then totals.
 * Trap: output order is first-seen order (not sorted, not hash order); words are
 * lower-cased and split on non-alphabetic characters.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define NBUCKET 101

struct entry {
    char *word;
    int count;
    int order;
    struct entry *next;
};

static struct entry *table[NBUCKET];
static struct entry *seen[4096];
static int nseen = 0;

static unsigned int hash(const char *s)
{
    unsigned int h = 0;
    while (*s) h = h * 33 + (unsigned char)*s++;
    return h % NBUCKET;
}

static void add(const char *w)
{
    unsigned int h = hash(w);
    struct entry *e;
    for (e = table[h]; e; e = e->next)
        if (strcmp(e->word, w) == 0) { e->count++; return; }
    if (nseen >= 4096) return;
    e = malloc(sizeof *e);
    e->word = malloc(strlen(w) + 1);
    strcpy(e->word, w);
    e->count = 1;
    e->order = nseen;
    e->next = table[h];
    table[h] = e;
    seen[nseen++] = e;
}

int main(int argc, char **argv)
{
    int c, len = 0, i, total = 0, shown = 0;
    int min = argc > 1 ? atoi(argv[1]) : 2;
    char w[64];
    while ((c = getchar()) != EOF) {
        if (isalpha(c)) {
            if (len < 63) w[len++] = (char)tolower(c);
        } else if (len) {
            w[len] = 0; add(w); len = 0; total++;
        }
    }
    if (len) { w[len] = 0; add(w); total++; }
    for (i = 0; i < nseen; i++)
        if (seen[i]->count >= min) { printf("%-12s %4d\n", seen[i]->word, seen[i]->count); shown++; }
    printf("words=%d unique=%d shown=%d\n", total, nseen, shown);
    return 0;
}
