
from kathryn import *

##################################################################
#
# EASY MEM — a few mem_blks with a read/write call per bank
#
##################################################################

_DEFAULT_BANKS = 4


class EasyMem(Module):
    """A handful of memory banks, indexed like a list."""

    def __init__(self, data_width: int = 32, index_width: int = 8, blk_request: int = 4):
        super().__init__()
        self.data_width  = data_width
        self.index_width = index_width
        self.blk_request = blk_request

    @init
    def com_declare(self):

        self.mempool = []
        for blk_id in range(self.blk_request):
            blk = mem_blk(self.data_width, self.index_width, "blk{}".format(blk_id))
            self.mempool.append(blk)

    def read(self, blk_id : int, read_addr):

        return mem_ele(self.mempool[blk_id],
                       read_addr,
                       self.data_width,
                       True,
                       "read{}".format(blk_id))


    def write(self, blk_id : int, write_addr, data):
        x = mem_ele(self.mempool[blk_id], write_addr, self.data_width, False, "write{}".format(blk_id))
        x |= data