/* ticket_ids.c - issues ticket ids per queue using static local state.
 * Trap: static locals persist across calls; next_id() and the per-queue counters must keep state.
 */
#include <stdio.h>
#include <string.h>

static int next_id(void)
{
    static int id = 1000;
    id += 7;
    return id;
}

static const char *tag(const char *queue)
{
    static char buf[32];
    static int calls = 0;
    calls++;
    sprintf(buf, "%c%c-%02d", queue[0], queue[1] ? queue[1] : 'X', calls % 100);
    return buf;
}

int main(void)
{
    char q[32];
    int per_queue[3] = {0, 0, 0};
    while (scanf("%31s", q) == 1) {
        const char *t1 = tag(q);
        int idx = q[0] == 'a' ? 0 : (q[0] == 'b' ? 1 : 2);
        per_queue[idx]++;
        printf("%s %d (queue %d, #%d)\n", t1, next_id(), idx, per_queue[idx]);
    }
    printf("totals %d %d %d\n", per_queue[0], per_queue[1], per_queue[2]);
    return 0;
}
