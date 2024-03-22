import math
from typing import Literal, TypedDict

from nicegui import ui

from virtual_memory import *

# %% 工具函数 %% #
unit_table = {0: '字节', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB', 5: 'PB', 6: 'EB', 7: 'ZB', 8: 'YB'}
def show_data_size(size: int):
  """将空间大小转换为为带单位的字符串"""
  base = 0
  while size % 1024 == 0:
    size //= 1024
    base += 1
  if base > 8:
    size <<= (base - 8) * 10
    base = 8
  return f"{size} {unit_table[base]}"

# %% 参数 %% #
class Parameters(TypedDict):
  block_size: int
  physical_block_count: int
  cache_set_count: int
  associativity: int
  virtual_mem_addr_width: int
  page_size: int
  tlb_line_count: int

def reset_parameters(params: Parameters):
  params["block_size"] = 32
  params["physical_block_count"] = 2048
  params["cache_set_count"] = 64
  params["associativity"] = 1
  params["virtual_mem_addr_width"] = 32
  params["page_size"] = 2048
  params["tlb_line_count"] = 32

params = Parameters() # type: ignore
reset_parameters(params)

# %% 模拟器 %% #
class LogPrinter(Printer):
  def __init__(self, log: ui.log):
    self.log = log
  def __call__(
    self,
    *values: object,
    sep: str | None = " ",
    end: str | None = "\n"
  ):
    if sep is None: sep = " "
    self.log.push(sep.join(str(x) for x in values))

def initialize_sim(params):
  global physical_mem, cache, virtual_mem, tlb
  cache_printer = LogPrinter(log_cache)
  physical_mem = PhysicalMemory(
    size=params["physical_block_count"] * params["block_size"],
    block_size=params["block_size"],
    printer=cache_printer
  )
  cache = SetAssocCache(
    physical=physical_mem,
    size=params["cache_set_count"] * params["associativity"] * params["block_size"],
    associativity=params["associativity"],
    printer=cache_printer
  )
  virtual_mem = VirtualMemory(
    main_mem=cache,
    size=1 << params["virtual_mem_addr_width"],
    page_size=params["page_size"],
    printer=LogPrinter(log_page_table)
  )
  tlb = FullyAssocTLB(
    virtual_mem=virtual_mem,
    size=params["tlb_line_count"],
    printer=LogPrinter(log_tlb)
  )

# %% 访问列表 %% #
access_index = -1
access_list = list[tuple[Literal['R', 'W'], int]]()
access_list_line_list = list[tuple[ui.label, ui.label]]()

# %% 访问 %% #
def access():
  global access_index
  if access_index + 1 >= len(access_list):
    ui.notify("已经执行到操作列表末尾，请先添加访问操作！")
    return
  if access_index >= 0:
    for label in access_list_line_list[access_index]:
      label.classes(remove="bg-yellow")
  access_index += 1
  mode, addr = access_list[access_index]
  if mode == 'R':
    tlb.read(addr)
  else:
    tlb.write(addr)
  update_tlb_table()
  update_page_table()
  update_cache_table()
  for label in access_list_line_list[access_index]:
    label.classes("bg-yellow")

with ui.stepper() as stepper:
  stepper.classes("m-auto")
  with ui.step("设定参数"):
    with ui.grid(columns=2):
      
      # %% 主存参数 %% #
      ui.label("主存参数").classes("col-span-2 font-bold text-lg")
      
      input_block_size = ui.select(
        [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024],
        label="块大小/字节"
      ).bind_value(params, "block_size")
      
      input_physical_block_count = ui.number(
        "主存块数",
        min=1, step=1,
        format="%d"
      ).bind_value(params, "physical_block_count", forward=int)
      
      show_physical_mem_size = ui.input("主存大小")
      show_physical_mem_size.bind_value_from(
        params,
        "physical_block_count",
        lambda _: show_data_size(params["physical_block_count"] * params["block_size"])
      )
      show_physical_mem_size.disable()
      
      def show_addr_width_str():
        block_no = int(math.ceil(math.log2(params["physical_block_count"])))
        block_addr = int(math.log2(params["block_size"]))
        return f"{block_no + block_addr} = {block_no} + {block_addr}"
      show_addr_width = ui.input("物理地址位数 = 块号 + 块内地址")
      show_addr_width.bind_value_from(
        params,
        "physical_block_count",
        lambda _: show_addr_width_str()
      )
      show_addr_width.disable()
      
      # %% Cache 参数 %% #
      ui.label("Cache 参数").classes("col-span-2 font-bold text-lg")
            
      input_cache_set_count = ui.number(
        "Cache 组数",
        min=1, step=1,
        format="%d"
      ).bind_value(params, "cache_set_count", forward=int)
      
      input_associativity = ui.select(
        {1: "直接映射", 2: "2 路组相联", 4: "4 路组相联", 8: "8 路组相联"},
        label="相联度"
      ).bind_value(params, "associativity")
      
      show_cache_size = ui.input("Cache 块数")
      show_cache_size.bind_value_from(
        params,
        "cache_set_count",
        lambda _: params["cache_set_count"] * params["associativity"]
      )
      show_cache_size.disable()
      
      show_cache_size = ui.input("Cache 大小")
      show_cache_size.bind_value_from(
        params,
        "cache_set_count",
        lambda _: show_data_size(params["cache_set_count"] * params["associativity"] * params["block_size"])
      )
      show_cache_size.disable()
      
      # %% 虚拟内存参数 %% #
      ui.label("虚拟内存参数").classes("col-span-2 font-bold text-lg")
      
      input_virtual_mem_addr_width = ui.number(
        "虚拟地址位数",
        min=13, step=1,
        format="%d"
      ).bind_value(params, "virtual_mem_addr_width", forward=int)
      
      show_virtual_mem_space = ui.input("虚拟地址空间")
      show_virtual_mem_space.bind_value_from(
        params,
        "virtual_mem_addr_width",
        lambda x: show_data_size(1 << x)
      )
      show_virtual_mem_space.disable()
      
      input_page_size = ui.select(
        [256, 512, 1024, 2048, 4096, 8192],
        label="页面大小/字节"
      ).bind_value(params, "page_size")
      
      input_tlb_line_count = ui.number(
        "TLB 行数（全相联）",
        min=1, step=1,
        format="%d"
      ).bind_value(params, "tlb_line_count", forward=int)
    
    # %% 切换按钮 %% #
    with ui.stepper_navigation():
      ui.button("开始模拟", on_click=lambda _: (
        stepper.next(),
        initialize_sim(params),
        update_tlb_table(),
        update_page_table(),
        update_cache_table(),
        update_virt_addr_transform(),
        update_cache_addr_comp()
      ))
      ui.button("重置参数", on_click=lambda _: reset_parameters(params)).props('flat')
  with ui.step("执行模拟"):
    with ui.row(wrap=False):
      with ui.column().classes("w-auto"):
        ui.column().classes("w-96")
        with ui.column().classes("fixed w-96 items-stretch"):
          # %% 访问顺序 %% #
          ui.label("访问顺序").classes("col-span-2 font-bold text-lg")
          with ui.card().classes("h-64"):
            show_access_list = (
              ui.grid()
              .classes("w-full gap-0 overflow-y-scroll")
              .style("grid-template-columns: min-content auto;")
            )
          with ui.row(wrap=False):
            access_list_line = {
              "mode": "R",
              "address": 0,
              "validate": True
            }
            input_access_mode = ui.select(
              {"R": "读", "W": "写"},
              label="操作",
              value="R"
            ).classes("w-20")
            input_access_mode.bind_value_to(access_list_line, "mode")
            def parse_hex_number(x):
              try:
                access_list_line["address"] = int(x, base=16)
                access_list_line["validate"] = True
              except ValueError:
                access_list_line["validate"] = False
            def validate_hex_number(x):
              try: int(x, base=16)
              except ValueError: return False
              return True
            input_access_addr = ui.input(
              "地址",
              value="0",
              on_change=lambda e: parse_hex_number(e.value),
              validation={"请输入十六进制数字": validate_hex_number}
            )
          with ui.row(wrap=False):
            def access_list_append():
              access_list.append((access_list_line["mode"], access_list_line["address"]))
              with show_access_list:
                access_list_line_list.append((
                  ui.label({"R": "读", "W": "写"}[access_list_line["mode"]]).classes("pr-2"),
                  ui.label(f"{access_list_line['address']:#x}")
                ))
            def access_list_clear():
              global access_index
              access_index = -1
              access_list.clear()
              show_access_list.clear()
              access_list_line_list.clear()
              
              # new added, to clear the log info on the right side
              log_tlb.clear()
              log_page_table.clear()
              log_cache.clear()
            ui.button(
              "添加",
              on_click=access_list_append
            ).bind_enabled_from(access_list_line, "validate")
            # TODO　ui.button("导入").props('flat')
            ui.button(
              "清空",
              on_click=lambda _: access_list_clear()
            ).props('flat')

          # %% 切换按钮 %% #
          with ui.row():
            ui.button("单步执行", on_click=lambda _: (
              access(),
              update_virt_addr_transform(),
              update_cache_addr_comp()
            ))
            ui.button("连续执行", on_click=lambda _: (
              [access() for _ in range(len(access_list) - access_index - 1)],
              update_virt_addr_transform(),
              update_cache_addr_comp()
            ))
            ui.button("重置模拟", on_click=lambda _: (
              access_list_clear(),
              initialize_sim(params),
              update_tlb_table(),
              update_page_table(),
              update_cache_table(),
              update_virt_addr_transform(),
              update_cache_addr_comp()
            )).props('flat')
            ui.button("重设参数", on_click=stepper.previous).props('flat')

      with ui.timeline(side="right"):
        # %% TLB %% #
        with ui.timeline_entry(title="TLB"):
          show_virt_addr_transform = ui.html()
          def update_virt_addr_transform():
            addr = 0
            if 0 <= access_index < len(access_list):
              _, addr = access_list[access_index]
            addr_bin = bin(addr)[2:].zfill(params["virtual_mem_addr_width"])
            virt_addr_width = params["virtual_mem_addr_width"]
            page_addr_width = int(math.log2(params["page_size"]))
            phys_addr_width = int(math.log2(physical_mem.size))
            page_addr = addr % params["page_size"]
            if addr // params["page_size"] in virtual_mem.page_table:
              phys_page = virtual_mem.page_table[addr // params["page_size"]].physical
              phys_addr = phys_page * params["page_size"] + page_addr
            else:
              phys_page = 0
              phys_addr = 0
            phys_addr_bin = bin(phys_addr)[2:].zfill(phys_addr_width)
            show_virt_addr_transform.set_content(f"""
              <table class="border-separate">
                <tr>
                  <td class='font-bold pr-1'>虚地址</td>
                  {"".join(f"<td class='w-4 text-center'>{d}</td>" for d in addr_bin)}
                </tr>
                <tr class="text-xs text-center">
                  <td></td>
                  <td class="border-black border-l border-b">{virt_addr_width - 1}</td>
                  <td class="border-black border-b"
                      colspan="{virt_addr_width - page_addr_width - 2}">
                    虚页号 = {addr // params["page_size"]:#x}
                  </td>
                  <td class="border-black border-b border-r">{page_addr_width}</td>
                  <td class="border-black border-l border-b">{page_addr_width - 1}</td>
                  <td class="border-black border-b" colspan="{page_addr_width - 2}">
                    页内地址 = {page_addr:#x}
                  </td>
                  <td class="border-black border-b border-r">0</td>
                </tr>
                <tr class="text-xs text-center">
                  <td colspan="{virt_addr_width - phys_addr_width + 1}"></td>
                  <td class="border-black border-l border-t">{phys_addr_width - 1}</td>
                  <td class="border-black border-t text-center"
                      colspan="{phys_addr_width - page_addr_width - 2}">
                    实页号
                  </td>
                  <td class="border-black border-t border-r">{page_addr_width}</td>
                  <td class="border-black border-l border-t">{page_addr_width - 1}</td>
                  <td class="border-black border-t text-center" colspan="{page_addr_width - 2}">
                    页内地址 = {page_addr:#x}
                  </td>
                  <td class="border-black border-t border-r">0</td>
                </tr>
                <tr>
                  <td class='font-bold pr-1'>实地址</td>
                  <td colspan="{virt_addr_width - phys_addr_width}"></td>
                  {"".join(f"<td class='w-4 text-center'>{d}</td>" for d in phys_addr_bin)}
                </tr>
              </table>
            """)
          with ui.row(wrap=False):
            columns = [
              {"name": "id", "label": "行号", "field": "id"},
              {"name": "valid", "label": "有效", "field": "valid"},
              {"name": "dirty", "label": "脏", "field": "dirty"},
              {"name": "dirty_dirty", "label": "修改", "field": "dirty_dirty"},
              {"name": "virtual", "label": "虚页号", "field": "virtual"},
              {"name": "physical", "label": "实页号", "field": "physical"}
            ]
            show_tlb_table = ui.table(columns, []).classes("h-64")
            def update_tlb_table():
              show_tlb_table.rows = [
                dict(
                  id=i,
                  valid=["否", "是"][line.valid],
                  **{
                    "dirty": ["否", "是"][line.dirty],
                    "dirty_dirty": ["否", "是"][line.dirty_dirty],
                    "virtual": f"{line.virtual:#x}",
                    "physical": f"{line.physical:#x}"
                  } if line.valid else dict()
                )
                for i, line in enumerate(tlb.table)
              ]
            log_tlb = ui.log().classes("self-stretch w-64 whitespace-pre-line font-s")
        # %% 页表 %% #
        with ui.timeline_entry(title="页表"):
          btn_randomize_page_table = ui.button(
            "随机化页表",
            on_click=lambda _: (
              virtual_mem.randomize_page_table(0.5),
              update_page_table()
            )
          )
          with ui.row(wrap=False):
            columns = [
              {"name": "id", "label": "虚页号", "field": "id"},
              {"name": "valid", "label": "有效", "field": "valid"},
              {"name": "dirty", "label": "脏", "field": "dirty"},
              {"name": "physical", "label": "实页号", "field": "physical"}
            ]
            show_page_table = ui.table(columns, []).classes("h-64")
            def update_page_table():
              sorted_keys = sorted(virtual_mem.page_table.keys())
              ids = []
              if len(sorted_keys) > 0:
                if sorted_keys[0] != 0:
                  ids.append(-1)
                ids.append(sorted_keys[0])
              for i, id in enumerate(sorted_keys[1:]):
                if id - sorted_keys[i] != 1:
                  ids.append(-1)
                ids.append(id)
              if len(sorted_keys) > 0:
                if sorted_keys[-1] != virtual_mem.size // virtual_mem.page_size - 1:
                  ids.append(-1)
              if len(sorted_keys) == 0:
                ids.append(-1)
              show_page_table.rows = [
                {
                  "id": f"{id:#x}",
                  "valid": "是",
                  "dirty": ["否", "是"][virtual_mem.page_table[id].dirty],
                  "physical": f"{virtual_mem.page_table[id].physical:#x}"
                } if id >= 0 else {
                  "id": "...",
                  "valid": "否"
                }
                for id in ids
              ]
            log_page_table = ui.log().classes("self-stretch w-64 whitespace-pre-line font-s")
        # %% Cache %% #
        with ui.timeline_entry(title="Cache"):
          show_cache_addr_comp = ui.html()
          def update_cache_addr_comp():
            addr = 0
            if 0 <= access_index < len(access_list):
              _, addr = access_list[access_index]
            page_addr = addr % params["page_size"]
            phys_addr_width = int(math.log2(physical_mem.size))
            if addr // params["page_size"] in virtual_mem.page_table:
              phys_page = virtual_mem.page_table[addr // params["page_size"]].physical
              phys_addr = phys_page * params["page_size"] + page_addr
            else:
              phys_page = 0
              phys_addr = 0
            phys_addr_bin = bin(phys_addr)[2:].zfill(phys_addr_width)
            block_width = int(math.log2(params["block_size"]))
            set_width = int(math.log2(params["cache_set_count"]))
            tag_width = phys_addr_width - block_width - set_width
            show_cache_addr_comp.set_content(f"""
              <table class="border-separate">
                <tr>
                  <td class='font-bold pr-1'>实地址</td>
                  {"".join(f"<td class='w-4 text-center'>{d}</td>" for d in phys_addr_bin)}
                </tr>
                <tr class="text-xs text-center">
                  <td></td>
                  <td class="border-black border-l border-b">{phys_addr_width - 1}</td>
                  <td class="border-black border-b text-center"
                      colspan="{tag_width - 2}">
                    标记
                  </td>
                  <td class="border-black border-b border-r">{set_width + block_width}</td>
                  <td class="border-black border-l border-b">{set_width + block_width - 1}</td>
                  <td class="border-black border-b text-center"
                      colspan="{set_width - 2}">
                    组号
                  </td>
                  <td class="border-black border-b border-r">{block_width}</td>
                  <td class="border-black border-l border-b">{block_width - 1}</td>
                  <td class="border-black border-b text-center" colspan="{block_width - 2}">
                    块内地址
                  </td>
                  <td class="border-black border-b border-r">0</td>
                </tr>
              </table>
            """)
          with ui.row(wrap=False):
            columns = [
              {"name": "id", "label": "组号", "field": "id"},
              {"name": "way", "label": "组内块号", "field": "way"},
              {"name": "valid", "label": "有效", "field": "valid"},
              {"name": "dirty", "label": "脏", "field": "dirty"},
              {"name": "tag", "label": "标记", "field": "tag"},
              {"name": "timer", "label": "计时器", "field": "timer"}
            ]
            show_cache_table = ui.table(columns, []).classes("h-64")
            def update_cache_table():
              show_cache_table.rows = [
                dict(
                  id=idx,
                  way=way,
                  valid=["否", "是"][line.valid],
                  **{
                    "dirty": ["否", "是"][line.dirty],
                    "tag": f"{line.tag:#x}",
                    "timer": f"{line.timer}"
                  } if line.valid else dict()
                )
                for idx, set_ in enumerate(cache.data)
                for way, line in enumerate(set_)
              ]
            log_cache = ui.log().classes("self-stretch w-64 whitespace-pre-line font-s")

ui.run(
  title="虚拟内存模拟器",
  language="zh-CN",
  port=2050
)
