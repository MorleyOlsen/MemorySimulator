from collections import deque
from dataclasses import dataclass
import math
import random
from typing import Protocol

class Printer(Protocol):
  def __call__(
    self,
    *values: object,
    sep: str | None = " ",
    end: str | None = "\n"
  ): ...

@dataclass(frozen=True)
class PrinterWithPrefix:
  prefix: str
  
  def __call__(
    self,
    *values: object,
    sep: str | None = " ",
    end: str | None = "\n"
  ):
    print(self.prefix, *values, sep=sep, end=end)

class PhysicalMemory:
  """物理内存"""

  size: int # 内存大小
  block_size: int # 块大小
  printer: Printer # 消息输出器
  
  def __init__(
    self,
    size: int = 1 << 16,
    block_size: int = 32,
    printer: Printer = print
  ):
    """
    :param size: 内存大小
    :param block_size: 块大小
    """
    assert size % block_size == 0, "内存大小必须是块大小的整数倍"
    self.size = size
    self.block_size = block_size
    self.printer = printer
  
  def read(self, addr: int):
    """读一个内存地址，返回 True"""
    assert addr >= 0 and addr < self.size, "物理内存地址不可越界"
    self.printer(f"读物理内存块 {addr // self.block_size:#x}")
  
  def write(self, addr: int):
    """写一个内存地址，返回 True"""
    assert addr >= 0 and addr < self.size, "物理内存地址不可越界"
    self.printer(f"写物理内存块 {addr // self.block_size:#x}")

class SetAssocCache:
  """组相联 cache"""
  
  @dataclass
  class Line:
    """cache 行
    
    :param tag: 标记
    :param valid: 有效位
    :param dirty: 脏位
    :param timer: LRU 计时器
    """
    tag: int = 0                 # 标记
    valid: bool = False          # 有效位
    dirty: bool = False          # 脏位
    timer: int = 0               # LRU 计时器

  physical: PhysicalMemory       # 物理内存
  size: int                      # 大小
  associativity: int             # 相联度
  block_size: int                # 块大小
  data: list[list[Line]]         # 目录表
  printer: Printer
  
  def __init__(
    self,
    physical: PhysicalMemory,
    size: int = 2 << 10,
    associativity: int = 1,
    printer: Printer = print
  ):
    """
    :param physical: 物理内存
    :param size: cache 大小
    :param associativity: 相联度
    """
    assert size % (associativity * physical.block_size) == 0, "cache 大小必须是相联度与块大小的乘积的整数倍"
    self.physical = physical
    self.size = size
    self.associativity = associativity
    self.block_size = physical.block_size
    self.data = [
      [self.Line() for _ in range(associativity)]
      for _ in range(size // (associativity * self.block_size))
    ]
    self.printer = printer
  
  def _get_addr_info(self, addr: int):
    """由内存地址计算 (标记, cache 组号, 块内地址)"""
    transp_size = self.size // self.associativity # 每组在内存地址上算同一块，如同 Cache 大小减小一般
    tag = addr // transp_size
    idx = (addr % transp_size) // self.block_size
    block_addr = addr % transp_size % self.block_size
    return (tag, idx, block_addr)
  
  def _get_addr(self, tag: int, idx: int, block_addr: int):
    """由 (标记, cache 组号, 块内地址) 计算内存地址"""
    return tag * (self.size // self.associativity) + idx * self.block_size + block_addr
  
  def _swap_in(self, tag: int, idx: int):
    """给定标记和 cache 组号，调入一个块，返回组内块号"""
    assert tag >= 0 and tag < math.ceil(self.physical.size / self.size), "标记不可越界"
    assert idx >= 0 and idx < len(self.data), "块号不可越界"
    way = next((way for way in range(self.associativity) if not self.data[idx][way].valid), None)
    if way is None:
      self.printer("Cache 组已满，需要调出")
      way = max(range(self.associativity), key=lambda way: self.data[idx][way].timer)
      self._swap_out(idx, way)
    line = self.data[idx][way]
    self.physical.read(self._get_addr(tag, idx, 0))
    self.printer("从内存读取一个块")
    line.tag = tag
    line.valid = True
    line.dirty = False
    return way
  
  def _swap_out(self, idx: int, way: int):
    """给定 cache 组号和组内块号，调出一个块"""
    assert idx >= 0 and idx < len(self.data), "组号不可越界"
    assert way >= 0 and way < self.associativity, "组内块号不可越界"
    block = idx * self.associativity + way
    line = self.data[idx][way]
    assert line.valid, "只有当 cache 块有效时才能调出"
    if line.dirty:
      self.printer(f"cache 块 {block:#x} 为脏块，需要写回")
      self.physical.write(self._get_addr(line.tag, idx, 0))
    else:
      self.printer(f"cache 块 {block:#x} 非脏块，无需写回")
    line.valid = False
  
  def read(self, addr: int):
    """读一个内存地址，返回是否命中"""
    assert addr >= 0 and addr < self.physical.size, "物理内存地址不可越界"
    (tag, idx, block_addr) = self._get_addr_info(addr)
    line = next((line for line in self.data[idx] if line.valid and line.tag == tag), None)
    if line is not None: # 命中
      self.printer("cache 命中，读取 cache 块")
    else: # 不命中
      self.printer("cache 不命中，需要调入")
      way = self._swap_in(tag, idx)
      line = self.data[idx][way]
    line.timer = 0
    for line in self.data[idx]: line.timer += 1
  
  def write(self, addr: int):
    """写一个内存地址，返回是否命中
    
    写策略：写回法、按写分配
    """
    assert addr >= 0 and addr < self.physical.size, "物理内存地址不可越界"
    (tag, idx, block_addr) = self._get_addr_info(addr)
    line = next((line for line in self.data[idx] if line.valid and line.tag == tag), None)
    if line is not None: # 命中
      self.printer("cache 命中，读取 cache 块")
    else: # 不命中
      self.printer("cache 不命中，需要调入")
      way = self._swap_in(tag, idx)
      line = self.data[idx][way]
    line.dirty = True
    line.timer = 0
    for line in self.data[idx]: line.timer += 1

  def invalidate(self, begin: int, end: int):
    """将一段内存的 cache 无效化，即将对应的块全部调出
    
    :param begin: 内存地址范围开始
    :param end: 内存地址范围末尾
    """
    for addr in range(begin - begin % self.block_size, end, self.block_size):
      (tag, idx, _) = self._get_addr_info(addr)
      way = next((
        way for way in range(self.associativity)
        if self.data[idx][way].valid and self.data[idx][way].tag == tag
      ), None)
      if way is not None:
        self._swap_out(idx, way)

class VirtualMemory:
  """虚拟内存空间
  
  本模拟器不考虑辅存的情况，并且直接使用 Python 的集合类型处理了主存空间分配问题。
  """
  
  @dataclass
  class Page:
    """页表中的一行（没有有效位，因为使用了字典模拟）
    
    :param physical: 实页号
    :param dirty: 脏位
    """
    physical: int = 0
    dirty: bool = False
  
  main_mem: SetAssocCache             # 主存
  size: int                           # 虚拟地址空间大小
  page_size: int                      # 页面大小
  page_table: dict[int, Page]         # 页表（为了性能使用字典而非列表实现）
  frame_set: set[int]                 # 空闲页框集
  lru_queue: deque[int]               # LRU 算法的队列
  printer: Printer
  
  def __init__(
    self,
    main_mem: SetAssocCache,
    size: int = 1 << 32,
    page_size: int = 2 << 10,
    printer: Printer = print
  ):
    """
    :param main_mem: 主存
    :param size: 虚拟内存空间大小
    :param page_size: 页面大小
    """
    assert size % page_size == 0, "虚拟内存空间大小必须是页面大小的整数倍"
    self.main_mem = main_mem
    self.size = size
    self.page_size = page_size
    self.page_table = dict()
    self.frame_set = {i for i in range(self.main_mem.physical.size // self.page_size)}
    self.lru_queue = deque()
    self.printer = printer

  def randomize_page_table(self, mem_usage: float):
    """随机化页表。本函数必须在初始化后立即使用
    
    :param mem_usage: 物理内存占用率
    """
    assert 0 <= mem_usage <= 1, "占用率必须在 [0, 1] 范围内"
    for page, frame in enumerate(random.sample(
      list(self.frame_set),
      k=int(mem_usage * len(self.frame_set))
    )):
      line = self.page_table.setdefault(page, self.Page())
      line.physical = frame
      self.frame_set.remove(frame)
      self.lru_queue.append(page)
  
  def _swap_in(self, page: int):
    """向主存装入一个虚页，若发生写回则返回被换出的虚页号"""
    assert page >= 0 and page < self.size // self.page_size, "虚页号不可越界"
    assert page not in self.page_table, "只有当虚页未装入时才能装入"
    line = self.page_table.setdefault(page, self.Page())
    line.dirty = False
    swapped = None
    
    # LRU
    if len(self.frame_set) == 0: # 若主存已满
      self.printer("主存已满，需要写回一个页")
      swapped = self.lru_queue[0]
      self._swap_out(self.lru_queue[0]) # 将最久未访问过的页写回
    
    line.physical = self.frame_set.pop()
    self.lru_queue.append(page)
    self.printer(f"将虚页 {page:#x} 装入主存")
    return swapped
  
  def _swap_out(self, page: int):
    """从主存写回一个虚页"""
    assert page >= 0 and page < self.size // self.page_size, "虚页号不可越界"
    assert page in self.page_table, "只有当虚页已装入时才能写回"
    line = self.page_table[page]
    self.printer("将虚页 {page:#x} 所对应的实页的所有 cache 全部作废")
    self.main_mem.invalidate( # 写回虚页前，必须确保主存的 cache 全部无效
      line.physical * self.page_size,
      (line.physical + 1) * self.page_size
    )
    if line.dirty:
      self.printer(f"向辅存写回虚页 {page:#x}")
    self.frame_set.add(line.physical)
    self.lru_queue.remove(page)
    del self.page_table[page]
  
  def read(self, addr: int):
    """读一个虚地址，返回是否在主存中"""
    assert addr >= 0 and addr < self.size, "虚地址不可越界"
    page = addr // self.page_size
    page_addr = addr % self.page_size
    if page in self.page_table: # 在主存中
      self.printer("虚页在主存中")
      self.lru_queue.remove(page)
      self.lru_queue.append(page)
    else: # 缺页
      self.printer("缺页，从辅存中装入")
      self._swap_in(page)
    line = self.page_table[page]
    phys_addr = line.physical * self.page_size + page_addr
    self.main_mem.read(phys_addr)

  def write(self, addr: int):
    """写一个虚地址，返回是否在主存中"""
    assert addr >= 0 and addr < self.size, "虚地址不可越界"
    page = addr // self.page_size
    page_addr = addr % self.page_size
    if page in self.page_table: # 在主存中
      self.printer("虚页在主存中")
      self.lru_queue.remove(page)
      self.lru_queue.append(page)
    else: # 缺页
      self.printer("缺页，从辅存中装入")
      self._swap_in(page)
    line = self.page_table[page]
    phys_addr = line.physical * self.page_size + page_addr
    self.main_mem.write(phys_addr)
    line.dirty = True

class FullyAssocTLB:
  """全相联快表"""
  
  @dataclass
  class Line:
    """快表中的一行

    :param virtual: 虚页号
    :param physical: 实页号
    :param valid: 有效位
    :param dirty: 脏位
    :param dirty_dirty: 脏位是否被修改
    """
    virtual: int = 0
    physical: int = 0
    valid: bool = False
    dirty: bool = False
    dirty_dirty: bool = False
  
  virtual_mem: VirtualMemory # 主页表
  table: list[Line] # 快表数据
  lru_queue: deque[int] # LRU 算法的队列
  printer: Printer
  
  def __init__(
    self,
    virtual_mem: VirtualMemory,
    size: int = 32,
    printer: Printer = print
  ):
    """
    :param virtual_mem: 主页表
    :param size: 容量
    """
    self.virtual_mem = virtual_mem
    self.table = [self.Line() for _ in range(size)]
    self.lru_queue = deque()
    self.printer = printer

  def _swap_in(self, page: int):
    """换入一行，返回换入的行号"""
    assert page >= 0 and page < self.virtual_mem.size // self.virtual_mem.page_size, "虚页号不可越界"
    idx = next((i for i, line in enumerate(self.table) if not line.valid), None)
    if idx is None:
      self.printer("TLB 已满，需要换出一行")
      idx = self.lru_queue[0]
      self._swap_out(idx) # 将最久未访问的行写回
    if page not in self.virtual_mem.page_table:
      swapped = self.virtual_mem._swap_in(page)
      if swapped is not None:
        self.printer("虚拟内存发生写回，将 TLB 中的对应行无效化")
        swapped_idx = next((i for i, line in enumerate(self.table) if line.virtual == swapped), None)
        if swapped_idx is not None:
          self._swap_out(swapped_idx)
    source_line = self.virtual_mem.page_table[page]
    line = self.table[idx]
    line.valid = True
    line.dirty = source_line.dirty
    line.dirty_dirty = False
    line.virtual = page
    line.physical = source_line.physical
    self.printer(f"将虚页 {page:#x} 的页表行读取到 TLB")
    return idx
  
  def _swap_out(self, idx: int):
    """换出一行
    
    :param idx: 行号
    """
    assert 0 <= idx < len(self.table), "行号不可越界"
    if self.table[idx].dirty_dirty:
      self.printer("TLB 脏位被修改，需要写回页表")
      self.virtual_mem.page_table[self.table[idx].virtual].dirty = True
    self.table[idx].valid = False
    self.lru_queue.remove(idx)
    self.printer(f"令虚页 {self.table[idx].virtual:#x} 在 TLB 中的对应行失效")
  
  def read(self, addr: int):
    """读一个虚地址"""
    assert addr >= 0 and addr < self.virtual_mem.size, "虚地址不可越界"
    page = addr // self.virtual_mem.page_size
    page_addr = addr % self.virtual_mem.page_size
    idx = next((i for i, line in enumerate(self.table) if line.valid and line.virtual == page), None)
    if idx is not None:
      line = self.table[idx]
      self.printer("虚页在 TLB 中，直接访问内存")
      self.virtual_mem.main_mem.read(line.physical * self.virtual_mem.page_size + page_addr)
    else:
      self.printer("虚页不在 TLB 中，需要查页表，并将页表行存入 TLB")
      self.virtual_mem.read(addr)
      self._swap_in(page)
    
  def write(self, addr: int):
    """写一个虚地址"""
    assert addr >= 0 and addr < self.virtual_mem.size, "虚地址不可越界"
    page = addr // self.virtual_mem.page_size
    page_addr = addr % self.virtual_mem.page_size
    idx = next((i for i, line in enumerate(self.table) if line.valid and line.virtual == page), None)
    if idx is not None:
      line = self.table[idx]
      self.printer("虚页在 TLB 中，直接访问内存")
      self.virtual_mem.main_mem.write(line.physical * self.virtual_mem.page_size + page_addr)
      if not (line.dirty or line.dirty_dirty):
        line.dirty = True
        line.dirty_dirty = True
    else:
      self.printer("虚页不在 TLB 中，需要查页表，并将页表行存入 TLB")
      self.virtual_mem.write(addr)
      self._swap_in(page)
