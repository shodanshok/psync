#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <dirent.h>
#include <stddef.h>
#include <signal.h>
#include <sys/inotify.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <stdbool.h>
#include <sys/timeb.h>

#define MAXEXCLUDES 16      // Max number of excludes
#define MAXDIRS 1000000     // Max number of watched dir
#define BUFFSIZE 16384      // 16K should be sufficient for any filename
#define SEPARATOR ":"   // Field separator

// Command line options
bool debug = false;
bool quiet = false;
bool stats = false;

// Global vars
int inotify_fd;
char *excludes[MAXEXCLUDES] = {NULL};
char *wd_list[MAXDIRS] = {NULL};
char moved_from_fullpath[BUFFSIZE] = {0};
char moved_to_fullpath[BUFFSIZE] = {0};
uint32_t moved_from_cookie = 0;
uint32_t moved_to_cookie = 0;

// For profile purpose
struct timeb start_time, stop_time;

void profile_start() {
    ftime(&start_time);
}

void profile_stop(char *string) {
    ftime(&stop_time);
    int msecs;
    long int mstart, mstop;
    mstart = start_time.time * 1000 + start_time.millitm;
    mstop = stop_time.time * 1000 + stop_time.millitm;
    msecs = mstop - mstart;
    stats ? printf("info: Elapsed time (msecs), %s: %d\n", string, msecs) : 0;
}

// Utility functions
char * normalize_dir(char *dirname, bool strip) {
    char *normalized;
    int l;
    if (dirname == NULL) {
        return NULL;
    }
    l = strlen(dirname)-1;
    while (l) {
        if (dirname[l] == '/') {
            dirname[l] = 0;
        } else {
            break;
        }
        l--;
    }
    if (strip) {
        normalized = dirname;
    } else {
        asprintf(&normalized, "%s/", dirname);
    }
    return normalized;
}

int dironly(const struct dirent *entry) {
    int i;
    if (entry->d_type != DT_DIR || strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
        return 0;
    }
    for (i = 0; i < MAXEXCLUDES; i++) {
        if (excludes[i]) {
            if (strstr(entry->d_name, excludes[i])) {
                return 0;
            }
        }
    }
    return 1;
}

int noempty(const struct dirent *entry) {
    if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
        return 0;
    }
    return 1;
}

// Free (eventually) allocated memory
void reset_wd(int wd) {
    if (wd_list[wd]) {
        free(wd_list[wd]);
    }
    wd_list[wd] = NULL;
}

void reset_wd_list() {
    int i;
    for (i = 0; i < MAXDIRS; i++) {
        if (wd_list[i]) {
            reset_wd(i);
        }
    }
}

// Add single watch
int add_watch(char *dirname) {
    int wd;
    wd = inotify_add_watch(inotify_fd, dirname, (IN_CREATE | IN_CLOSE_WRITE | IN_MOVE | IN_MOVE_SELF | IN_DELETE | IN_UNMOUNT | IN_Q_OVERFLOW | IN_IGNORED));
    if (wd < 0) {
        printf("error: Can not establish watch for dir %s\n", dirname);
        fflush(stdout);
    } else if (wd >= MAXDIRS) {
        printf("error: No more empty slots in wd_list (capacity: %d). Exiting\n", MAXDIRS);
        fflush(stdout);
        sleep(5);
        exit(1);
    } else {
        reset_wd(wd);
        asprintf(&wd_list[wd], "%s/", dirname);
        quiet ? 0 : printf("info: Watcher ID %d, dir %s/\n", wd, dirname);
    }
    return wd;
}

// Recursive scan and watch
int recursive_watch(char *dirname, bool toplevel) {
    struct dirent **content = NULL;
    int i, ndirs;
    char *fullpath;
    dirname = normalize_dir(dirname, true);
    if (toplevel) {
        add_watch(dirname);
    }
    ndirs = scandir(dirname, &content, dironly, NULL);
    for (i = 0; i < ndirs; ++i) {
        if (asprintf(&fullpath, "%s/%s", dirname, content[i]->d_name)) {
            add_watch(fullpath);
            free(fullpath);
        }
    }
    for (i = 0; i < ndirs; ++i) {
        if (asprintf(&fullpath, "%s/%s", dirname, content[i]->d_name)) {
            free(content[i]);
            recursive_watch(fullpath, false);
            free(fullpath);
        }
    }
    free(content);
    return ndirs;
}

/*void rename_dir(char *from, char *to) {
    struct dirent **content;
    int i, from_size;
    char *dirname;
    from_size = strlen(from);
    if (!scandir(to, &content, noempty, NULL)) {
        return;
    }
    for (i = 0; i < MAXDIRS; i++) {
        dirname = wd_list[i];
        if (dirname) {
            if (strstr(dirname, from)) {
                asprintf(&wd_list[i], "%s%s", to, dirname+from_size);
                free(dirname);
            }
        }
    }
}

void rename_dir_self(int i, char *from, char *to) {
    char *dirname;
    dirname = wd_list[i];
    asprintf(&wd_list[i], "%s", to);
    free(dirname);
} */


// Event print and handling
void event_print(struct inotify_event *event, char *event_name, char *dirname, char *from, char *to, bool always) {
    char *tofree = NULL;
    if (event->mask & IN_ISDIR) {
        asprintf(&event_name, "%s,ISDIR", event_name);
        tofree = event_name;
    }
    if (always || debug) {
        printf("%s%s%s%s%s%s%s%s\n", event_name, SEPARATOR, dirname, SEPARATOR, from, SEPARATOR, to, SEPARATOR);
    }
    free(tofree);
}

void manage_event(struct inotify_event *event) {
    char *fullpath = NULL;
    char *event_name = NULL;
    if (event->len) {
        if (event->mask & IN_ISDIR) {
            asprintf(&fullpath, "%s%s/", wd_list[event->wd], event->name);
        } else {
            asprintf(&fullpath, "%s%s", wd_list[event->wd], event->name);
        }
    } else {
        asprintf(&fullpath, "%s", wd_list[event->wd]);
    }
    switch (event->mask & (IN_ALL_EVENTS | IN_UNMOUNT | IN_Q_OVERFLOW | IN_IGNORED)) {
        case IN_UNMOUNT:
            event_name = "UNMOUNT";
            reset_wd_list();
            break;
        case IN_Q_OVERFLOW:
            event_name = "OVERFLOW";
            break;
        case IN_IGNORED:
            event_name = "IGNORED";
            event_print(event, event_name, wd_list[event->wd], fullpath, fullpath, false);
            reset_wd(event->wd);
            break;
        case IN_ACCESS:
            event_name = "ACCESS";
            break;
        case IN_ATTRIB:
            event_name = "ATTRIB";
            break;
        case IN_CLOSE_WRITE:
            event_name = "CLOSE_WRITE";
            event_print(event, event_name, wd_list[event->wd], fullpath, fullpath, true);
            break;
        case IN_CLOSE_NOWRITE:
            event_name = "CLOSE_NOWRITE";
            break;
        case IN_CREATE:
            event_name = "CREATE";
            event_print(event, event_name, wd_list[event->wd], fullpath, fullpath, true);
            if (event->mask & IN_ISDIR) {
                recursive_watch(fullpath, true);
            }
            break;
        case IN_DELETE:
            event_name = "DELETE";
            event_print(event, event_name, wd_list[event->wd], fullpath, fullpath, true);
            break;
        case IN_DELETE_SELF:
            event_name = "DELETE_SELF";
            event_print(event, event_name, wd_list[event->wd], fullpath, fullpath, false);
            reset_wd(event->wd);
            break;
        case IN_MODIFY:
            event_name = "MODIFY";
            break;
        case IN_MOVE_SELF:
            event_name = "MOVE_SELF";
            event_print(event, event_name, wd_list[event->wd], fullpath, fullpath, false);
            break;
        case IN_MOVED_FROM:
            event_name = "MOVED_FROM";
            moved_from_cookie = event->cookie;
            strncpy(moved_from_fullpath, fullpath, BUFFSIZE);
            strncpy(moved_to_fullpath, "\0", BUFFSIZE);
            event_print(event, event_name, wd_list[event->wd], moved_from_fullpath, moved_from_fullpath, false);
            break;
        case IN_MOVED_TO:
            event_name = "MOVED_TO";
            moved_to_cookie = event->cookie;
            strncpy(moved_to_fullpath, fullpath, BUFFSIZE);
            event_print(event, event_name, wd_list[event->wd], moved_to_fullpath, moved_to_fullpath, false);
            if (moved_from_cookie == moved_to_cookie) {
                event_print(event, "MOVE", wd_list[event->wd], moved_from_fullpath, moved_to_fullpath, true);
            } else {
                event_print(event, "MOVE", wd_list[event->wd], moved_to_fullpath, moved_to_fullpath, true);
            }
            if (event->mask & IN_ISDIR) {
                profile_start();
                recursive_watch(moved_to_fullpath, true);
                profile_stop("renaming directory");
            }
            break;
        case IN_OPEN:
            event_name = "OPEN";
            break;
        default:
            event_name = "UNKNOW";
            printf("error: Unrecognized event with mask %x\n", event->mask);
            moved_from_cookie = 0;
            moved_to_cookie = 0;
            break;
    }
    free(fullpath);
    fflush(stdout);
}

// Option parsing
char * parse_options(int argc, char **argv) {
    char option;
    char *dir;
    int e;
    e = 0;
    while ((option = getopt (argc, argv, "dE:qs")) != -1) {
        switch (option) {
            case 'd':
                debug = true;
                break;
            case 'E':
                e++;
                if (e < MAXEXCLUDES) {
                    excludes[e] = optarg;
                }
                break;
            case 'q':
                quiet = true;
                break;
            case 's':
                stats = true;
                break;
            case '?':
                return NULL;
            default:
                return NULL;
        }
    }
    if (optind == argc) {
        return NULL;
    }
    dir = argv[optind];
    if (argc - optind > 1) {
        printf("error: Exactly one directory permitted.\nIgnoring any subsequent specified directory\n");
        fflush(stdout);
    }
    return dir;
}

// Main loop
int main(int argc, char **argv) {
    int rbytes;
    int event_size, event_offset;
    char buffer[BUFFSIZE];
    char *dir;
    struct inotify_event *event;
    dir = parse_options(argc, argv);
    inotify_fd = inotify_init();
    if (inotify_fd < 0) {
        printf("error: Can not initialize inotify\n");
        fflush(stdout);
        sleep(5);
        return 1;
    }
    if (dir == NULL) {
        printf("error: No directory specified\n");
        fflush(stdout);
        sleep(5);
        return 1;
    }
    profile_start();
    recursive_watch(dir, true);
    profile_stop("establishing watches");
    while (1) {
        rbytes = read(inotify_fd, buffer, sizeof(buffer));
        if (rbytes < 0) {
            printf("error: Fatal error while reading events\n");
            fflush(stdout);
            sleep(5);
            return 1;
        }
        for (event_offset = 0; event_offset < rbytes; event_offset = event_offset+event_size) {
            event = (struct inotify_event *) &buffer[event_offset];
            event_size = sizeof(struct inotify_event) + event->len;
            manage_event(event);
        }
    }
    return 0;
}
