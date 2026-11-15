# MIEngine normally terminates a launch with the console "kill" command.
# Detach from a disk-backed guest instead; the post-debug task syncs and shuts
# it down through its private control port, preserving guest filesystem data.
python
import gdb
kernel_persistent_confirm = gdb.parameter('confirm')
gdb.execute('set confirm off')
def kernel_detach_persistent_guest():
    if gdb.selected_inferior().pid:
        gdb.execute('detach')
end

define kill
    python kernel_detach_persistent_guest()
end

define hook-quit
    python kernel_detach_persistent_guest()
end

python
gdb.set_parameter('confirm', kernel_persistent_confirm)
end
